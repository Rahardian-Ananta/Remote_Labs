"""Job Dispatcher handling FIFO queuing, node dispatching, and robust fault-handling semantics."""

import asyncio
from datetime import datetime, timezone
import logging
from typing import Optional
import httpx

from common.hashing import compute_cache_key, sha256_hash
from common.jsonrpc import EXECUTOR_BUSY
from common.models import JobMetadata, JobStatus
from scheduler.cache import SchedulerEdgeCache
from scheduler.db import SchedulerDB
from scheduler.dht_client import DHTClient
from scheduler.registry import ExecutorRegistry
from scheduler.rpc_client import RPCClientError, SchedulerRPCClient

logger = logging.getLogger("scheduler.dispatcher")


class JobDispatcher:
    """Async background dispatcher that assigns queued jobs to eligible executors with at-most-once fault tolerance."""

    def __init__(
        self,
        db: SchedulerDB,
        registry: ExecutorRegistry,
        rpc_client: SchedulerRPCClient,
        edge_cache: SchedulerEdgeCache,
        dht_client: DHTClient,
        poll_interval_sec: float = 0.5,
    ):
        self.db = db
        self.registry = registry
        self.rpc_client = rpc_client
        self.edge_cache = edge_cache
        self.dht_client = dht_client
        self.poll_interval_sec = poll_interval_sec
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._active_dispatches: set[asyncio.Task] = set()

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._dispatch_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        # Wait for in-flight dispatches to settle
        if self._active_dispatches:
            for t in list(self._active_dispatches):
                t.cancel()

    async def reconcile_running_jobs_on_startup(self) -> None:
        """Section 8.3: On restart, reconcile any job recorded as RUNNING.

        - If getStatus returns completed -> save result.
        - If JOB_NOT_FOUND -> re-queue (was not executed).
        - If executor unreachable -> mark FAILED with EXECUTOR_LOST.
        """
        running_jobs = self.db.get_running_jobs()
        if not running_jobs:
            return

        logger.info(f"Reconciling {len(running_jobs)} RUNNING job(s) from previous scheduler session...")
        for job in running_jobs:
            if not job.executor_id:
                job.status = JobStatus.QUEUED
                self.db.update_job(job)
                continue

            rec = self.registry.get(job.executor_id)
            if not rec:
                job.status = JobStatus.FAILED
                job.failure_reason = "EXECUTOR_LOST"
                self.db.update_job(job)
                continue

            try:
                status_info = await self.rpc_client.get_status(rec.url, job.job_id)
                if status_info is None:
                    # JOB_NOT_FOUND -> re-queue
                    job.status = JobStatus.QUEUED
                    job.executor_id = None
                    self.db.update_job(job)
                elif status_info.get("status") in [JobStatus.SUCCESS.value, JobStatus.FAILED.value, JobStatus.TIMEOUT.value]:
                    job.status = JobStatus(status_info["status"])
                    job.exit_code = status_info.get("exit_code")
                    job.duration_ms = status_info.get("duration_ms")
                    job.result_key = status_info.get("result_key")
                    job.preview = status_info.get("preview")
                    job.finished_at = datetime.now(timezone.utc).isoformat()
                    self.db.update_job(job)
                else:
                    # Still running
                    pass
            except Exception:
                job.status = JobStatus.FAILED
                job.failure_reason = "EXECUTOR_LOST"
                self.db.update_job(job)

    async def _dispatch_loop(self) -> None:
        while self._running:
            try:
                job = self.db.dequeue_next_queued()
                if not job:
                    await asyncio.sleep(self.poll_interval_sec)
                    continue

                # Select an eligible executor
                executor = self.registry.select_executor(job.job_type, job.num_ranks)
                if not executor:
                    # No healthy or available executor right now; put back to QUEUED
                    job.status = JobStatus.QUEUED
                    self.db.update_job(job)
                    await asyncio.sleep(self.poll_interval_sec)
                    continue

                # Launch execution in independent async task
                t = asyncio.create_task(self._execute_job_task(job, executor.executor_id, executor.url))
                self._active_dispatches.add(t)
                t.add_done_callback(self._active_dispatches.discard)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in dispatcher loop: {e}", exc_info=True)
                await asyncio.sleep(self.poll_interval_sec)

    async def _execute_job_task(self, job: JobMetadata, executor_id: str, executor_url: str) -> None:
        """Executes a single job with at-most-once and fault-recovery guarantees."""
        now = datetime.now(timezone.utc).isoformat()
        job.status = JobStatus.RUNNING
        job.executor_id = executor_id
        job.started_at = now
        job.attempts += 1
        self.db.update_job(job)

        rec = self.registry.get(executor_id)
        if rec:
            rec.running_jobs += 1

        try:
            # Execute RPC with strict failure handling
            result = None
            max_retries = 2
            backoff_sec = 0.5

            for attempt in range(max_retries + 1):
                try:
                    result = await self.rpc_client.execute_code(
                        executor_url=executor_url,
                        job_id=job.job_id,
                        job_type=job.job_type,
                        source_code=job.source_code,
                        timeout_sec=job.timeout_sec,
                        num_ranks=job.num_ranks,
                        tags=job.tags,
                    )
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout) as conn_err:
                    # Connection refused or connect timeout: DEFINITELY not executed on worker
                    logger.warning(f"Connect error to {executor_id}: {conn_err}. Re-queuing job {job.job_id}.")
                    job.status = JobStatus.QUEUED
                    job.executor_id = None
                    self.db.update_job(job)
                    self.registry.update_ping_failure(executor_id)
                    return
                except (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ReadError) as read_err:
                    # Read timeout or connection broken after send: AMBIGUOUS (might have executed)
                    logger.warning(f"Read error on attempt {attempt} for {job.job_id}: {read_err}")
                    if attempt < max_retries:
                        await asyncio.sleep(backoff_sec)
                        backoff_sec *= 2.0
                        continue
                    else:
                        # Retries exhausted. Query getStatus on the same executor
                        try:
                            st = await self.rpc_client.get_status(executor_url, job.job_id)
                            if st and st.get("status") in [JobStatus.SUCCESS.value, JobStatus.FAILED.value, JobStatus.TIMEOUT.value]:
                                job.status = JobStatus(st["status"])
                                job.exit_code = st.get("exit_code")
                                job.duration_ms = st.get("duration_ms")
                                job.result_key = st.get("result_key")
                                job.preview = st.get("preview")
                                job.finished_at = datetime.now(timezone.utc).isoformat()
                                self.db.update_job(job)
                                return
                        except Exception:
                            pass

                        # Unreachable executor: do NOT move to another node! Mark FAILED EXECUTOR_LOST
                        job.status = JobStatus.FAILED
                        job.failure_reason = "EXECUTOR_LOST"
                        job.finished_at = datetime.now(timezone.utc).isoformat()
                        self.db.update_job(job)
                        self.registry.update_ping_failure(executor_id)
                        return
                except RPCClientError as rpc_err:
                    if rpc_err.code == EXECUTOR_BUSY:
                        # Executor busy: safely re-queue job for another node or retry
                        logger.info(f"Executor {executor_id} is busy; re-queuing job {job.job_id}")
                        job.status = JobStatus.QUEUED
                        job.executor_id = None
                        self.db.update_job(job)
                        return

                    # RPC error response from worker
                    job.status = JobStatus.FAILED
                    job.failure_reason = str(rpc_err)
                    job.finished_at = datetime.now(timezone.utc).isoformat()
                    self.db.update_job(job)
                    return

            if result:
                job.status = result.status
                job.exit_code = result.exit_code
                job.duration_ms = result.duration_ms
                job.result_key = result.result_key
                job.preview = result.preview
                job.truncated = result.truncated
                job.finished_at = datetime.now(timezone.utc).isoformat()
                self.db.update_job(job)

                # If deterministic caching enabled, save to edge cache
                if job.cache and job.status == JobStatus.SUCCESS:
                    det_key = compute_cache_key(job.job_type, job.source_code, job.num_ranks, job.timeout_sec)
                    etag = sha256_hash(f"{job.job_id}:{job.finished_at}")
                    cache_payload = {
                        "job_id": job.job_id,
                        "status": job.status.value,
                        "exit_code": job.exit_code,
                        "duration_ms": job.duration_ms,
                        "preview": job.preview,
                        "result_key": job.result_key,
                        "from_cache": True,
                    }
                    self.edge_cache.put(det_key, cache_payload, etag, associated_job_ids=[job.job_id])

        finally:
            if rec:
                rec.running_jobs = max(0, rec.running_jobs - 1)

