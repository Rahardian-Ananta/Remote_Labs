"""Persistent SQLite database for Scheduler job queue and execution metadata."""

from datetime import datetime, timezone
import json
import sqlite3
import threading
from typing import Any, Dict, List, Optional
from common.models import JobMetadata, JobStatus


class SchedulerDB:
    """Thread-safe SQLite store for job queue and metadata persistence."""

    def __init__(self, db_path: str = "scheduler.db"):
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
                    CREATE TABLE IF NOT EXISTS jobs (
                        job_id TEXT PRIMARY KEY,
                        job_type TEXT NOT NULL,
                        source_code TEXT NOT NULL,
                        timeout_sec INTEGER NOT NULL,
                        num_ranks INTEGER,
                        cache INTEGER NOT NULL DEFAULT 0,
                        tags TEXT NOT NULL DEFAULT '[]',
                        status TEXT NOT NULL,
                        executor_id TEXT,
                        result_key TEXT,
                        queued_at TEXT NOT NULL,
                        started_at TEXT,
                        finished_at TEXT,
                        duration_ms REAL,
                        failure_reason TEXT,
                        attempts INTEGER DEFAULT 0,
                        exit_code INTEGER,
                        preview TEXT,
                        truncated INTEGER DEFAULT 0
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
                conn.commit()

    def _row_to_model(self, row: sqlite3.Row) -> JobMetadata:
        tags = []
        try:
            tags = json.loads(row["tags"]) if row["tags"] else []
        except Exception:
            tags = []
        return JobMetadata(
            job_id=row["job_id"],
            job_type=row["job_type"],
            source_code=row["source_code"],
            timeout_sec=row["timeout_sec"],
            num_ranks=row["num_ranks"],
            cache=bool(row["cache"]),
            tags=tags,
            status=JobStatus(row["status"]),
            executor_id=row["executor_id"],
            result_key=row["result_key"],
            queued_at=row["queued_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            duration_ms=row["duration_ms"],
            failure_reason=row["failure_reason"],
            attempts=row["attempts"],
            exit_code=row["exit_code"],
            preview=row["preview"],
            truncated=bool(row["truncated"]),
        )

    def create_job(self, job: JobMetadata) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO jobs (
                        job_id, job_type, source_code, timeout_sec, num_ranks,
                        cache, tags, status, executor_id, result_key,
                        queued_at, started_at, finished_at, duration_ms,
                        failure_reason, attempts, exit_code, preview, truncated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job.job_id,
                        job.job_type,
                        job.source_code,
                        job.timeout_sec,
                        job.num_ranks,
                        1 if job.cache else 0,
                        json.dumps(job.tags),
                        job.status.value,
                        job.executor_id,
                        job.result_key,
                        job.queued_at,
                        job.started_at,
                        job.finished_at,
                        job.duration_ms,
                        job.failure_reason,
                        job.attempts,
                        job.exit_code,
                        job.preview,
                        1 if job.truncated else 0,
                    ),
                )
                conn.commit()

    def get_job(self, job_id: str) -> Optional[JobMetadata]:
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,))
                row = cur.fetchone()
                if row:
                    return self._row_to_model(row)
                return None

    def list_jobs(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[JobMetadata]:
        with self._lock:
            with self._get_connection() as conn:
                if status:
                    cur = conn.execute(
                        "SELECT * FROM jobs WHERE status = ? ORDER BY queued_at DESC LIMIT ? OFFSET ?",
                        (status, limit, offset),
                    )
                else:
                    cur = conn.execute(
                        "SELECT * FROM jobs ORDER BY queued_at DESC LIMIT ? OFFSET ?",
                        (limit, offset),
                    )
                return [self._row_to_model(r) for r in cur.fetchall()]

    def count_jobs(self, status: Optional[str] = None) -> int:
        with self._lock:
            with self._get_connection() as conn:
                if status:
                    cur = conn.execute("SELECT COUNT(*) FROM jobs WHERE status = ?", (status,))
                else:
                    cur = conn.execute("SELECT COUNT(*) FROM jobs")
                return cur.fetchone()[0]

    def dequeue_next_queued(self) -> Optional[JobMetadata]:
        """Fetch the oldest job in QUEUED status and atomically transition it to RUNNING."""
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute(
                    "SELECT * FROM jobs WHERE status = ? ORDER BY queued_at ASC LIMIT 1",
                    (JobStatus.QUEUED.value,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                job = self._row_to_model(row)
                now = datetime.now(timezone.utc).isoformat()
                job.status = JobStatus.RUNNING
                job.started_at = now
                conn.execute(
                    "UPDATE jobs SET status = ?, started_at = ? WHERE job_id = ?",
                    (JobStatus.RUNNING.value, now, job.job_id),
                )
                conn.commit()
                return job

    def update_job(self, job: JobMetadata) -> None:
        with self._lock:
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE jobs SET
                        status = ?, executor_id = ?, result_key = ?,
                        started_at = ?, finished_at = ?, duration_ms = ?,
                        failure_reason = ?, attempts = ?, exit_code = ?,
                        preview = ?, truncated = ?
                    WHERE job_id = ?
                    """,
                    (
                        job.status.value,
                        job.executor_id,
                        job.result_key,
                        job.started_at,
                        job.finished_at,
                        job.duration_ms,
                        job.failure_reason,
                        job.attempts,
                        job.exit_code,
                        job.preview,
                        1 if job.truncated else 0,
                        job.job_id,
                    ),
                )
                conn.commit()

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
                conn.commit()
                return cur.rowcount > 0

    def get_running_jobs(self) -> List[JobMetadata]:
        with self._lock:
            with self._get_connection() as conn:
                cur = conn.execute("SELECT * FROM jobs WHERE status = ?", (JobStatus.RUNNING.value,))
                return [self._row_to_model(r) for r in cur.fetchall()]

