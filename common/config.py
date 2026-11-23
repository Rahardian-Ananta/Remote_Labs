"""Configuration management for RemoteLab v2.0."""

import os
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


def parse_executors_env(raw: str) -> Dict[str, str]:
    """Parse EXECUTORS string like 'exec1=http://127.0.0.1:9001,exec2=http://127.0.0.1:9002' into a dictionary."""
    executors: Dict[str, str] = {}
    if not raw or not raw.strip():
        return executors
    clean = raw.strip().strip('"').strip("'")
    for pair in clean.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" in pair:
            eid, url = pair.split("=", 1)
            executors[eid.strip()] = url.strip().rstrip("/")
        else:
            # fallback: treat as URL with generated ID
            url = pair.strip().rstrip("/")
            eid = f"exec_{hash(url) % 10000}"
            executors[eid] = url
    return executors


def parse_bootstrap_nodes_env(raw: str) -> List[str]:
    """Parse comma-separated list of bootstrap node URLs."""
    if not raw or not raw.strip():
        return []
    clean = raw.strip().strip('"').strip("'")
    return [url.strip().rstrip("/") for url in clean.split(",") if url.strip()]


class SchedulerConfig(BaseModel):
    """Scheduler configuration model."""
    host: str = Field(default_factory=lambda: os.getenv("SCHEDULER_HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("SCHEDULER_PORT", "8000")))
    executors: Dict[str, str] = Field(
        default_factory=lambda: parse_executors_env(
            os.getenv("EXECUTORS", "exec1=http://127.0.0.1:9001,exec2=http://127.0.0.1:9002,exec3=http://127.0.0.1:9003")
        )
    )
    scheduling_policy: str = Field(default_factory=lambda: os.getenv("SCHEDULING_POLICY", "least_loaded").lower())
    health_interval_sec: float = Field(default_factory=lambda: float(os.getenv("HEALTH_INTERVAL_SEC", "2.0")))
    db_path: str = Field(default_factory=lambda: os.getenv("DB_PATH", "scheduler.db"))
    cache_capacity: int = Field(default_factory=lambda: int(os.getenv("CACHE_CAPACITY", "100")))
    cache_lease_sec: float = Field(default_factory=lambda: float(os.getenv("CACHE_LEASE_SEC", "30.0")))


class ExecutorConfig(BaseModel):
    """Executor configuration model."""
    executor_id: str = Field(default_factory=lambda: os.getenv("EXECUTOR_ID", "exec1"))
    executor_url: Optional[str] = Field(default_factory=lambda: os.getenv("EXECUTOR_URL"))
    host: str = Field(default_factory=lambda: os.getenv("EXECUTOR_HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("EXECUTOR_PORT", "9001")))
    capacity: int = Field(default_factory=lambda: int(os.getenv("EXECUTOR_CAPACITY", "2")))
    max_ranks: int = Field(default_factory=lambda: int(os.getenv("MAX_RANKS", "4")))
    max_output_bytes: int = Field(default_factory=lambda: int(os.getenv("MAX_OUTPUT_BYTES", "1048576")))
    memory_limit_mb: int = Field(default_factory=lambda: int(os.getenv("MEMORY_LIMIT_MB", "256")))
    # Empty means "auto": ExecutorRPCServer falls back to executor_<id>_dedup.db
    db_path: str = Field(default_factory=lambda: os.getenv("EXECUTOR_DB_PATH", ""))

    # Chord DHT Configuration
    chord_m: int = Field(default_factory=lambda: int(os.getenv("CHORD_M", "32")))
    chord_replication: int = Field(default_factory=lambda: int(os.getenv("CHORD_REPLICATION", "2")))
    chord_maintenance_sec: float = Field(default_factory=lambda: float(os.getenv("CHORD_MAINTENANCE_SEC", "1.0")))
    bootstrap_nodes: List[str] = Field(
        default_factory=lambda: parse_bootstrap_nodes_env(
            os.getenv("BOOTSTRAP_NODES", "http://127.0.0.1:9001,http://127.0.0.1:9002,http://127.0.0.1:9003")
        )
    )

