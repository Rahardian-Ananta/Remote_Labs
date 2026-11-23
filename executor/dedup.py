"""Persistent deduplication store (SQLite) for at-most-once execution semantics."""

import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from common.models import JobStatus


class DedupStore:
    """Thread-safe persistent deduplication store for an executor node."""

    def __init__(self, db_path: str = "executor_dedup.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS job_dedup (
                        job_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        exit_code INTEGER,
                        duration_ms REAL,
                        result_key TEXT,
                        preview TEXT,
                        truncated INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                conn.commit()

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Look up existing job status and cached result."""
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute("SELECT * FROM job_dedup WHERE job_id = ?", (job_id,))
                row = cur.fetchone()
                if row:
                    return {
                        "job_id": row["job_id"],
                        "status": JobStatus(row["status"]),
                        "exit_code": row["exit_code"],
                        "duration_ms": row["duration_ms"],
                        "result_key": row["result_key"],
                        "preview": row["preview"],
                        "truncated": bool(row["truncated"]),
                    }
                return None

    def register_start(self, job_id: str) -> bool:
        """Atomically register a new job in RUNNING state. Returns True if successfully registered,

        or False if job_id was already present (duplicate execution attempt).
        """
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._get_connection() as conn:
                try:
                    conn.execute(
                        """
                        INSERT INTO job_dedup (job_id, status, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (job_id, JobStatus.RUNNING.value, now, now),
                    )
                    conn.commit()
                    return True
                except sqlite3.IntegrityError:
                    return False

    def mark_completed(
        self,
        job_id: str,
        status: JobStatus,
        exit_code: int,
        duration_ms: float,
        result_key: str,
        preview: str,
        truncated: bool = False,
    ) -> None:
        """Store the final execution result for job_id."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE job_dedup
                    SET status = ?, exit_code = ?, duration_ms = ?, result_key = ?, preview = ?, truncated = ?, updated_at = ?
                    WHERE job_id = ?
                    """,
                    (
                        status.value,
                        exit_code,
                        duration_ms,
                        result_key,
                        preview,
                        1 if truncated else 0,
                        now,
                        job_id,
                    ),
                )
                conn.commit()

    def mark_cancelled(self, job_id: str) -> bool:
        """Mark a running job as CANCELLED."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(
                    """
                    UPDATE job_dedup
                    SET status = ?, updated_at = ?
                    WHERE job_id = ? AND status = ?
                    """,
                    (JobStatus.CANCELLED.value, now, job_id, JobStatus.RUNNING.value),
                )
                conn.commit()
                return cur.rowcount > 0

