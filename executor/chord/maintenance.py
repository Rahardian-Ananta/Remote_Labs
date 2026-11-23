"""Background maintenance tasks for Chord DHT ring stabilization and finger fixing."""

import asyncio
import logging
from typing import Optional
from executor.chord.node import ChordNode

logger = logging.getLogger("chord.maintenance")


class ChordMaintenance:
    """Manages periodic stabilize, fix_fingers, and check_predecessor loops."""

    def __init__(self, node: ChordNode, interval_sec: float = 1.0):
        self.node = node
        self.interval_sec = interval_sec
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def start(self) -> None:
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.node.stabilize()
                await self.node.fix_fingers()
                await self.node.check_predecessor()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Error in Chord maintenance loop: {e}")
            await asyncio.sleep(self.interval_sec)

