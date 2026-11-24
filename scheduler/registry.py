"""Executor registry with Attribute-Based Naming and load-aware matching."""

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from common.models import ExecutorHealthStatus


class ExecutorRecord(BaseModel):
    executor_id: str
    url: str
    status: ExecutorHealthStatus = ExecutorHealthStatus.HEALTHY
    running_jobs: int = 0
    capacity: int = 2
    attributes: Dict[str, Any] = Field(default_factory=dict)
    chord_id: int = 0
    last_seen: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    consecutive_failures: int = 0
    active_jobs: List[str] = Field(default_factory=list)
    last_job_id: Optional[str] = None
    last_job_status: Optional[str] = None
    last_job_duration_ms: Optional[int] = None


class ExecutorRegistry:
    """Manages registered executors, tracks attribute-based naming and health metrics."""

    def __init__(self, scheduling_policy: str = "least_loaded"):
        self.scheduling_policy = scheduling_policy.lower()
        self._lock = threading.Lock()
        self._executors: Dict[str, ExecutorRecord] = {}
        self._rr_index: int = 0

    def register(
        self,
        executor_id: str,
        url: str,
        capacity: int = 2,
        attributes: Optional[Dict[str, Any]] = None,
        chord_id: int = 0,
        status: ExecutorHealthStatus = ExecutorHealthStatus.HEALTHY,
        running_jobs: int = 0,
    ) -> ExecutorRecord:
        with self._lock:
            record = ExecutorRecord(
                executor_id=executor_id,
                url=url.rstrip("/"),
                status=status,
                running_jobs=running_jobs,
                capacity=capacity,
                attributes=attributes or {"language": "python", "mpi": True, "max_ranks": 4},
                chord_id=chord_id,
                last_seen=datetime.now(timezone.utc).isoformat(),
                consecutive_failures=0,
            )
            self._executors[executor_id] = record
            return record

    def get(self, executor_id: str) -> Optional[ExecutorRecord]:
        with self._lock:
            return self._executors.get(executor_id)

    def list_all(self) -> List[ExecutorRecord]:
        with self._lock:
            return list(self._executors.values())

    def get_all(self) -> List[ExecutorRecord]:
        return self.list_all()

    def update_ping_success(
        self,
        executor_id: str,
        status: ExecutorHealthStatus,
        running_jobs: int,
        capacity: int,
        attributes: Dict[str, Any],
        chord_id: int,
    ) -> None:
        with self._lock:
            if executor_id in self._executors:
                rec = self._executors[executor_id]
                rec.status = status
                rec.running_jobs = running_jobs
                rec.capacity = capacity
                rec.attributes = attributes
                rec.chord_id = chord_id
                rec.last_seen = datetime.now(timezone.utc).isoformat()
                rec.consecutive_failures = 0

    def update_ping_failure(self, executor_id: str, max_strikes: int = 1) -> None:
        with self._lock:
            if executor_id in self._executors:
                rec = self._executors[executor_id]
                rec.consecutive_failures += 1
                if rec.consecutive_failures >= max_strikes:
                    rec.status = ExecutorHealthStatus.UNAVAILABLE

    def select_executor(
        self,
        job_type: str,
        num_ranks: Optional[int] = None,
    ) -> Optional[ExecutorRecord]:
        """Select an eligible executor using Attribute-Based Naming and Scheduling Policy."""
        with self._lock:
            eligible: List[ExecutorRecord] = []
            for rec in self._executors.values():
                # Must be HEALTHY
                if rec.status != ExecutorHealthStatus.HEALTHY:
                    continue
                # Must have spare capacity
                if rec.running_jobs >= rec.capacity:
                    continue

                # Attribute-Based matching:
                attrs = rec.attributes
                if job_type == "mpi":
                    if not attrs.get("mpi", False):
                        continue
                    req_ranks = num_ranks or 1
                    if attrs.get("max_ranks", 4) < req_ranks:
                        continue

                eligible.append(rec)

            if not eligible:
                return None

            if self.scheduling_policy == "round_robin":
                self._rr_index = (self._rr_index + 1) % len(eligible)
                return eligible[self._rr_index]
            else:
                # Default: least_loaded (lowest running_jobs)
                eligible.sort(key=lambda r: (r.running_jobs / max(r.capacity, 1), r.running_jobs))
                return eligible[0]

