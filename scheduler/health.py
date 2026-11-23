"""Health Monitor for Executor nodes."""

import asyncio
import logging
from typing import Optional
from common.models import ExecutorHealthStatus
from scheduler.registry import ExecutorRegistry
from scheduler.rpc_client import SchedulerRPCClient

logger = logging.getLogger("scheduler.health")


class HealthMonitor:
    """Periodically pings all registered executors and tracks availability."""

    def __init__(
        self,
        registry: ExecutorRegistry,
        rpc_client: SchedulerRPCClient,
        interval_sec: float = 2.0,
    ):
        self.registry = registry
        self.rpc_client = rpc_client
        self.interval_sec = interval_sec
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _ping_one(self, rec) -> None:
        try:
            ping_res = await self.rpc_client.ping(rec.url)
            self.registry.update_ping_success(
                executor_id=rec.executor_id,
                status=ping_res.status,
                running_jobs=ping_res.running_jobs,
                capacity=ping_res.capacity,
                attributes=ping_res.attributes,
                chord_id=ping_res.chord_id,
            )
        except Exception as e:
            logger.debug(f"Health check failed for {rec.executor_id} ({rec.url}): {e}")
            self.registry.update_ping_failure(rec.executor_id)

    async def check_all_now(self) -> None:
        """Execute concurrent health check pass across all registered executors."""
        executors = self.registry.list_all()
        if executors:
            await asyncio.gather(*(self._ping_one(rec) for rec in executors), return_exceptions=True)

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                await self.check_all_now()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Health monitor loop error: {e}")
            await asyncio.sleep(self.interval_sec)

