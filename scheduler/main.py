"""Scheduler main entrypoint and FastAPI application."""

import contextlib
import logging
import os
from typing import AsyncGenerator
from fastapi import FastAPI, Response
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from common.config import SchedulerConfig
from scheduler.api import router as api_router
from scheduler.cache import SchedulerEdgeCache
from scheduler.db import SchedulerDB
from scheduler.dht_client import DHTClient
from scheduler.dispatcher import JobDispatcher
from scheduler.health import HealthMonitor
from scheduler.registry import ExecutorRegistry
from scheduler.rpc_client import SchedulerRPCClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("scheduler.main")

config = SchedulerConfig()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Initializing Scheduler services...")

    db = SchedulerDB(config.db_path)
    registry = ExecutorRegistry(scheduling_policy=config.scheduling_policy)
    rpc_client = SchedulerRPCClient(connect_timeout_sec=5.0)
    edge_cache = SchedulerEdgeCache(capacity=config.cache_capacity, lease_sec=config.cache_lease_sec)
    dht_client = DHTClient(registry, rpc_client)

    # Register initial executors from configuration
    for eid, url in config.executors.items():
        registry.register(executor_id=eid, url=url)
        logger.info(f"Configured initial executor: {eid} -> {url}")

    health_monitor = HealthMonitor(registry, rpc_client, interval_sec=config.health_interval_sec)
    dispatcher = JobDispatcher(db, registry, rpc_client, edge_cache, dht_client, poll_interval_sec=0.5)

    # Attach to app state
    app.state.db = db
    app.state.registry = registry
    app.state.rpc_client = rpc_client
    app.state.edge_cache = edge_cache
    app.state.dht_client = dht_client
    app.state.health_monitor = health_monitor
    app.state.dispatcher = dispatcher

    # Reconcile any left-over running jobs from previous sessions
    await dispatcher.reconcile_running_jobs_on_startup()

    # Start background tasks
    health_monitor.start()
    dispatcher.start()

    logger.info("Scheduler startup complete.")
    yield

    # Shutdown
    logger.info("Shutting down Scheduler services...")
    await dispatcher.stop()
    await health_monitor.stop()
    await rpc_client.aclose()
    logger.info("Scheduler shutdown complete.")


app = FastAPI(title="RemoteLab Scheduler", lifespan=lifespan)
app.include_router(api_router)


@app.get("/health")
async def health_check() -> dict:
    """Root health check probe for docker/uvicorn/monitoring."""
    reg = getattr(app.state, "registry", None)
    exec_count = len(reg.get_all()) if reg else 0
    return {"status": "ok", "service": "scheduler", "executors": exec_count}


# Mount static files directory if exists
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index() -> Response:
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>RemoteLab v2.0 Scheduler</h1><p>UI is initializing.</p>")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("SCHEDULER_PORT", str(config.port)))
    uvicorn.run("scheduler.main:app", host="0.0.0.0", port=port, log_level="info")
