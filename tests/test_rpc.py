"""Tests for executor JSON-RPC 2.0 interface and at-most-once semantics."""

import pytest
from common.jsonrpc import (
    EXECUTOR_BUSY,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JOB_NOT_FOUND,
    METHOD_NOT_FOUND,
)
from common.models import JobStatus
from executor.dedup import DedupStore
from executor.rpc_server import ExecutorRPCServer


@pytest.fixture
def rpc_server(tmp_path):
    db_file = str(tmp_path / "test_dedup.db")
    dedup = DedupStore(db_file)
    return ExecutorRPCServer(
        executor_id="test_exec",
        capacity=2,
        max_ranks=4,
        dedup_store=dedup,
    )


@pytest.mark.asyncio
async def test_rpc_invalid_request(rpc_server):
    # Missing jsonrpc 2.0 or method
    res = await rpc_server.handle_request({"bad": "body"})
    assert res.error is not None
    assert res.error.code == INVALID_REQUEST


@pytest.mark.asyncio
async def test_rpc_method_not_found(rpc_server):
    res = await rpc_server.handle_request({
        "jsonrpc": "2.0",
        "method": "unknownMethod",
        "params": {},
        "id": 1,
    })
    assert res.error is not None
    assert res.error.code == METHOD_NOT_FOUND


@pytest.mark.asyncio
async def test_rpc_ping(rpc_server):
    res = await rpc_server.handle_request({
        "jsonrpc": "2.0",
        "method": "ping",
        "params": {},
        "id": "ping-1",
    })
    assert res.error is None
    assert res.result["executor_id"] == "test_exec"
    assert res.result["status"] == "HEALTHY"
    assert res.result["capacity"] == 2
    assert res.result["attributes"]["language"] == "python"


@pytest.mark.asyncio
async def test_rpc_execute_code_and_at_most_once(rpc_server, tmp_path):
    # Test script increments counter in a persistent file
    counter_file = str(tmp_path / "counter.txt").replace("\\", "/")
    code = f"""
import os
val = 0
if os.path.exists("{counter_file}"):
    with open("{counter_file}", "r") as f:
        val = int(f.read().strip())
val += 1
with open("{counter_file}", "w") as f:
    f.write(str(val))
print(f"Counter: {{val}}")
"""
    job_id = "job-at-most-once-123"

    # First call: executes code
    req1 = {
        "jsonrpc": "2.0",
        "method": "executeCode",
        "params": {
            "job_id": job_id,
            "job_type": "python",
            "source_code": code,
            "timeout_sec": 5,
        },
        "id": "req-1",
    }
    res1 = await rpc_server.handle_request(req1)
    assert res1.error is None
    assert res1.result["status"] == JobStatus.SUCCESS
    assert "Counter: 1" in res1.result["preview"]

    # Second call with SAME job_id: MUST NOT execute again (at-most-once)
    req2 = {
        "jsonrpc": "2.0",
        "method": "executeCode",
        "params": {
            "job_id": job_id,
            "job_type": "python",
            "source_code": code,
            "timeout_sec": 5,
        },
        "id": "req-2",
    }
    res2 = await rpc_server.handle_request(req2)
    assert res2.error is None
    assert res2.result["status"] == JobStatus.SUCCESS
    assert "Counter: 1" in res2.result["preview"]

    # Verify counter file still has 1
    with open(counter_file, "r") as f:
        final_count = int(f.read().strip())
    assert final_count == 1, "Duplicate execution occurred! Expected 1, found {final_count}"


@pytest.mark.asyncio
async def test_rpc_get_status(rpc_server):
    # Non-existent job
    res = await rpc_server.handle_request({
        "jsonrpc": "2.0",
        "method": "getStatus",
        "params": {"job_id": "missing_job"},
        "id": 99,
    })
    assert res.error is not None
    assert res.error.code == JOB_NOT_FOUND


@pytest.mark.asyncio
async def test_rpc_capacity_busy(tmp_path):
    # Set capacity=1
    db_file = str(tmp_path / "busy_dedup.db")
    dedup = DedupStore(db_file)
    server = ExecutorRPCServer(
        executor_id="busy_exec",
        capacity=1,
        dedup_store=dedup,
    )
    # Fake one running job in running_jobs
    server.running_jobs["dummy_running"] = None

    req = {
        "jsonrpc": "2.0",
        "method": "executeCode",
        "params": {
            "job_id": "job-will-be-busy",
            "job_type": "python",
            "source_code": "print('busy')",
            "timeout_sec": 5,
        },
        "id": "busy-1",
    }
    res = await server.handle_request(req)
    assert res.error is not None
    assert res.error.code == EXECUTOR_BUSY

