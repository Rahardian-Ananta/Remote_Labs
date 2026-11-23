"""JSON-RPC 2.0 Server Stub for Executor Node."""

import asyncio
import logging
from typing import Any, Dict, Optional, Set
from fastapi import Request

from common.hashing import chord_hash, compute_cache_key, sha256_hash
from common.jsonrpc import (
    EXECUTOR_BUSY,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JOB_NOT_FOUND,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    JSONRPCResponse,
    error_response,
    success_response,
)
from common.models import (
    ExecuteCodeParams,
    ExecuteCodeResult,
    ExecutorAttributes,
    ExecutorHealthStatus,
    FullExecutionResult,
    JobStatus,
    JobType,
    PingResult,
)
from executor.chord.index import extract_search_tokens
from executor.chord.node import ChordNode
from executor.dedup import DedupStore
from executor.mpi_runner import execute_mpi_job
from executor.sandbox import execute_in_sandbox

logger = logging.getLogger("executor.rpc")


class ExecutorRPCServer:
    """Server Stub implementing JSON-RPC 2.0 interface for an executor."""

    def __init__(
        self,
        executor_id: str,
        capacity: int = 2,
        max_ranks: int = 4,
        max_output_bytes: int = 1048576,
        memory_limit_mb: int = 256,
        db_path: Optional[str] = None,
        dedup_store: Optional[DedupStore] = None,
        chord_node: Optional[ChordNode] = None,
    ):
        self.executor_id = executor_id
        self.capacity = capacity
        self.max_ranks = max_ranks
        self.max_output_bytes = max_output_bytes
        self.memory_limit_mb = memory_limit_mb
        self.dedup = dedup_store or DedupStore(db_path or f"executor_{executor_id}_dedup.db")
        self.chord = chord_node
        self.running_jobs: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def handle_request(self, body: Dict[str, Any], request_id: Optional[str] = None) -> JSONRPCResponse:
        """Route and execute JSON-RPC 2.0 request."""
        req_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}

        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not method:
            return error_response(req_id, INVALID_REQUEST, "Invalid JSON-RPC 2.0 Request")

        try:
            # 1. chord.* namespace
            if method.startswith("chord."):
                if not self.chord:
                    return error_response(req_id, INTERNAL_ERROR, "Chord DHT node not initialized")
                res = await self.chord.dispatch_local_rpc(method, params if isinstance(params, dict) else {})
                return success_response(req_id, res)

            # 2. ping
            if method == "ping":
                return success_response(req_id, (await self.ping()).model_dump())

            # 3. getStatus
            if method == "getStatus":
                job_id = params.get("job_id") if isinstance(params, dict) else (params[0] if params else None)
                if not job_id:
                    return error_response(req_id, INVALID_PARAMS, "Missing job_id parameter")
                res = await self.get_status(job_id)
                if res is None:
                    return error_response(req_id, JOB_NOT_FOUND, f"Job '{job_id}' not found")
                return success_response(req_id, res)

            # 4. cancelJob
            if method == "cancelJob":
                job_id = params.get("job_id") if isinstance(params, dict) else (params[0] if params else None)
                if not job_id:
                    return error_response(req_id, INVALID_PARAMS, "Missing job_id parameter")
                cancelled = await self.cancel_job(job_id)
                return success_response(req_id, {"cancelled": cancelled})

            # 5. executeCode
            if method == "executeCode":
                if isinstance(params, list):
                    return error_response(req_id, INVALID_PARAMS, "executeCode parameters must be a dictionary")
                try:
                    code_params = ExecuteCodeParams(**params)
                except Exception as p_err:
                    return error_response(req_id, INVALID_PARAMS, f"Invalid executeCode params: {p_err}")

                return await self.execute_code(req_id, code_params, request_id=request_id)

            return error_response(req_id, METHOD_NOT_FOUND, f"Method '{method}' not found")

        except Exception as ex:
            logger.exception(f"Unhandled exception handling RPC method {method}: {ex}")
            return error_response(req_id, INTERNAL_ERROR, str(ex))

    async def ping(self) -> PingResult:
        """Return executor health status, load, attributes, and Chord ID."""
        running_count = len(self.running_jobs)
        status = ExecutorHealthStatus.BUSY if running_count >= self.capacity else ExecutorHealthStatus.HEALTHY
        attrs = ExecutorAttributes(
            language="python",
            mpi=True,
            max_ranks=self.max_ranks,
            cpu_cores=4,
            memory_mb=self.memory_limit_mb,
        )
        chord_id = self.chord.node_id if self.chord else 0
        return PingResult(
            executor_id=self.executor_id,
            status=status,
            running_jobs=running_count,
            capacity=self.capacity,
            attributes=attrs.model_dump(),
            chord_id=chord_id,
        )

    async def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Look up job status in local dedup store."""
        return self.dedup.get(job_id)

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        async with self._lock:
            task = self.running_jobs.get(job_id)
            if task and not task.done():
                task.cancel()
                self.dedup.mark_cancelled(job_id)
                return True
        return self.dedup.mark_cancelled(job_id)

    async def execute_code(
        self,
        req_id: Optional[Any],
        params: ExecuteCodeParams,
        request_id: Optional[str] = None,
    ) -> JSONRPCResponse:
        """Execute Python or MPI code with at-most-once semantics and Chord result storage."""
        job_id = params.job_id

        # At-most-once check 1: Has this job already completed or currently running?
        existing = self.dedup.get(job_id)
        if existing:
            if existing["status"] == JobStatus.RUNNING:
                # Duplicate execution attempt while already running
                return success_response(
                    req_id,
                    ExecuteCodeResult(
                        job_id=job_id,
                        status=JobStatus.RUNNING,
                        exit_code=0,
                        duration_ms=0.0,
                        result_key=existing.get("result_key") or job_id,
                        preview="Job is already running",
                        truncated=False,
                    ).model_dump(),
                )
            else:
                # Already finished: return stored result without re-executing
                return success_response(
                    req_id,
                    ExecuteCodeResult(
                        job_id=job_id,
                        status=existing["status"],
                        exit_code=existing["exit_code"] or 0,
                        duration_ms=existing["duration_ms"] or 0.0,
                        result_key=existing["result_key"] or job_id,
                        preview=existing["preview"] or "",
                        truncated=existing["truncated"],
                    ).model_dump(),
                )

        # Capacity check
        async with self._lock:
            if len(self.running_jobs) >= self.capacity:
                return error_response(req_id, EXECUTOR_BUSY, f"Executor '{self.executor_id}' is busy")

            # At-most-once check 2: Atomic registration in SQLite
            registered = self.dedup.register_start(job_id)
            if not registered:
                # Concurrent insertion hit
                existing = self.dedup.get(job_id)
                if existing:
                    return success_response(req_id, existing)
                return error_response(req_id, EXECUTOR_BUSY, "Concurrent job registration conflict")

            task = asyncio.current_task()
            if task:
                self.running_jobs[job_id] = task

        # Perform actual execution
        try:
            if params.job_type == JobType.MPI:
                num_ranks = params.num_ranks or 2
                res = await execute_mpi_job(
                    source_code=params.source_code,
                    num_ranks=num_ranks,
                    max_ranks=self.max_ranks,
                    timeout_sec=params.timeout_sec,
                    max_output_bytes=self.max_output_bytes,
                    memory_limit_mb=self.memory_limit_mb,
                )
            else:
                res = await execute_in_sandbox(
                    source_code=params.source_code,
                    timeout_sec=params.timeout_sec,
                    max_output_bytes=self.max_output_bytes,
                    memory_limit_mb=self.memory_limit_mb,
                )

            # Store full result in Chord DHT
            combined_output = f"{res.stdout}\n{res.stderr}".strip()
            checksum = sha256_hash(combined_output)
            result_key = compute_cache_key(
                params.job_type.value,
                params.source_code,
                params.num_ranks,
                params.timeout_sec,
            )

            full_result = FullExecutionResult(
                job_id=job_id,
                stdout=res.stdout,
                stderr=res.stderr,
                exit_code=res.exit_code,
                duration_ms=res.duration_ms,
                sha256=checksum,
            )

            if self.chord:
                # Store full result by hash(job_id) and deterministic key
                job_key = f"job:{job_id}"
                await self.chord.handle_put(job_key, full_result.model_dump(), replicate=True)
                await self.chord.handle_put(result_key, full_result.model_dump(), replicate=True)

                # Index keywords in Chord inverted index
                tags_list = getattr(params, "tags", None) or []
                tokens = extract_search_tokens(tags=tags_list, stdout=res.stdout, max_tokens=20)
                for token in tokens:
                    self.chord.store.add_inverted_index(token, [job_id])

            preview = (res.stdout[:1024] if res.stdout else res.stderr[:1024])

            # Update persistent dedup record
            self.dedup.mark_completed(
                job_id=job_id,
                status=res.status,
                exit_code=res.exit_code,
                duration_ms=res.duration_ms,
                result_key=result_key,
                preview=preview,
                truncated=res.truncated,
            )

            exec_result = ExecuteCodeResult(
                job_id=job_id,
                status=res.status,
                exit_code=res.exit_code,
                duration_ms=res.duration_ms,
                result_key=result_key,
                preview=preview,
                truncated=res.truncated,
            )
            return success_response(req_id, exec_result.model_dump())

        finally:
            async with self._lock:
                self.running_jobs.pop(job_id, None)

