"""Tests for Scheduler crash recovery and state reconciliation on restart."""

import os
import time
import pytest
from common.models import JobMetadata, JobStatus
from scheduler.cache import SchedulerEdgeCache
from scheduler.db import SchedulerDB
from scheduler.dht_client import DHTClient
from scheduler.dispatcher import JobDispatcher
from scheduler.registry import ExecutorRegistry
from scheduler.rpc_client import SchedulerRPCClient


class DummyRPCClient(SchedulerRPCClient):
    """Stub RPC client to test specific recovery responses without network flakiness."""

    def __init__(self, status_map):
        super().__init__()
        self.status_map = status_map

    async def get_status(self, executor_url, job_id, request_id=None):
        if job_id in self.status_map:
            val = self.status_map[job_id]
            if val is None:
                return None
            return val
        raise ConnectionError("Executor dead")


@pytest.mark.asyncio
async def test_scheduler_reconciliation_on_restart(tmp_path):
    db_file = str(tmp_path / "recovery_test.db")
    db = SchedulerDB(db_file)

    # 1. Job 1: RUNNING in DB, but executor finished it
    db.create_job(
        JobMetadata(
            job_id="job-finished-during-crash",
            job_type="python",
            source_code="print(1)",
            timeout_sec=5,
            status=JobStatus.RUNNING,
            executor_id="exec1",
            queued_at="2026-10-31T00:00:00Z",
            started_at="2026-10-31T00:00:01Z",
        )
    )

    # 2. Job 2: RUNNING in DB, but executor never saw it (JOB_NOT_FOUND) -> re-queue
    db.create_job(
        JobMetadata(
            job_id="job-lost-before-exec",
            job_type="python",
            source_code="print(2)",
            timeout_sec=5,
            status=JobStatus.RUNNING,
            executor_id="exec1",
            queued_at="2026-10-31T00:00:00Z",
            started_at="2026-10-31T00:00:01Z",
        )
    )

    # 3. Job 3: RUNNING in DB, but executor completely unreachable / dead -> EXECUTOR_LOST
    db.create_job(
        JobMetadata(
            job_id="job-executor-dead",
            job_type="python",
            source_code="print(3)",
            timeout_sec=5,
            status=JobStatus.RUNNING,
            executor_id="exec_dead",
            queued_at="2026-10-31T00:00:00Z",
            started_at="2026-10-31T00:00:01Z",
        )
    )

    # 4. Job 4: QUEUED in DB -> remains QUEUED
    db.create_job(
        JobMetadata(
            job_id="job-still-queued",
            job_type="python",
            source_code="print(4)",
            timeout_sec=5,
            status=JobStatus.QUEUED,
            queued_at="2026-10-31T00:00:00Z",
        )
    )

    registry = ExecutorRegistry()
    registry.register("exec1", "http://127.0.0.1:9001")

    status_responses = {
        "job-finished-during-crash": {
            "status": "SUCCESS",
            "exit_code": 0,
            "duration_ms": 12.5,
            "result_key": "res-1",
            "preview": "Output 1",
        },
        "job-lost-before-exec": None,  # JOB_NOT_FOUND
    }

    rpc_client = DummyRPCClient(status_responses)
    edge_cache = SchedulerEdgeCache(capacity=50)
    dht_client = DHTClient(registry, rpc_client)

    dispatcher = JobDispatcher(db, registry, rpc_client, edge_cache, dht_client)

    # Trigger restart reconciliation
    await dispatcher.reconcile_running_jobs_on_startup()

    # Verify outcomes:
    j1 = db.get_job("job-finished-during-crash")
    assert j1.status == JobStatus.SUCCESS
    assert j1.exit_code == 0
    assert j1.preview == "Output 1"

    j2 = db.get_job("job-lost-before-exec")
    assert j2.status == JobStatus.QUEUED
    assert j2.executor_id is None

    j3 = db.get_job("job-executor-dead")
    assert j3.status == JobStatus.FAILED
    assert j3.failure_reason == "EXECUTOR_LOST"

    j4 = db.get_job("job-still-queued")
    assert j4.status == JobStatus.QUEUED

