"""Tests for Scheduler REST API endpoints and HTTP semantics."""

import pytest
import httpx
from common.config import SchedulerConfig
from scheduler.cache import SchedulerEdgeCache
from scheduler.db import SchedulerDB
from scheduler.dht_client import DHTClient
from scheduler.main import app
from scheduler.registry import ExecutorRegistry
from scheduler.rpc_client import SchedulerRPCClient


@pytest.fixture
async def api_client(tmp_path):
    db_file = str(tmp_path / "test_api_sched.db")
    config = SchedulerConfig()
    app.state.db = SchedulerDB(db_file)
    app.state.registry = ExecutorRegistry(scheduling_policy="least_loaded")
    app.state.rpc_client = SchedulerRPCClient(connect_timeout_sec=2.0)
    app.state.edge_cache = SchedulerEdgeCache(capacity=100, lease_sec=30.0)
    app.state.dht_client = DHTClient(app.state.registry, app.state.rpc_client)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_api_submit_job_validation(api_client):
    # Valid submission
    resp = await api_client.post(
        "/api/v1/jobs",
        json={"job_type": "python", "source_code": "print('ok')", "timeout_sec": 5},
    )
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "QUEUED"
    assert "job_id" in data
    assert "links" in data

    # Invalid timeout (> 30s)
    bad_resp = await api_client.post(
        "/api/v1/jobs",
        json={"job_type": "python", "source_code": "print('fail')", "timeout_sec": 60},
    )
    assert bad_resp.status_code == 422


@pytest.mark.asyncio
async def test_api_job_lifecycle_and_conditional_get(api_client):
    # Submit job
    resp = await api_client.post(
        "/api/v1/jobs",
        json={"job_type": "python", "source_code": "print('lifecycle')", "timeout_sec": 5},
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]

    # GET job
    get_resp = await api_client.get(f"/api/v1/jobs/{job_id}")
    assert get_resp.status_code == 200
    job_data = get_resp.json()
    assert job_data["job_id"] == job_id
    assert "ETag" in get_resp.headers
    etag = get_resp.headers["ETag"]

    # Conditional GET with If-None-Match -> 304 Not Modified
    cond_resp = await api_client.get(f"/api/v1/jobs/{job_id}", headers={"If-None-Match": etag})
    assert cond_resp.status_code == 304

    # Cancel job
    del_resp = await api_client.delete(f"/api/v1/jobs/{job_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["cancelled"] is True

    # Cancel already cancelled job -> 409 Conflict
    del_again = await api_client.delete(f"/api/v1/jobs/{job_id}")
    assert del_again.status_code == 409


@pytest.mark.asyncio
async def test_api_executors_and_health(api_client):
    # List executors
    exec_resp = await api_client.get("/api/v1/executors")
    assert exec_resp.status_code == 200
    assert "executors" in exec_resp.json()

    # Register new executor
    reg_resp = await api_client.post(
        "/api/v1/executors/register",
        json={
            "executor_id": "runtime_exec_99",
            "url": "http://127.0.0.1:9099",
            "capacity": 3,
            "attributes": {"language": "python", "mpi": True, "max_ranks": 4},
        },
    )
    assert reg_resp.status_code == 200
    assert reg_resp.json()["registered"] is True

    # Health check
    health_resp = await api_client.get("/api/v1/health")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert "queue" in health_data
    assert "cache" in health_data
