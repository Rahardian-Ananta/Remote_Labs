"""Pydantic data models for jobs, executor state, Chord DHT, and RPC calls."""

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class JobType(str, Enum):
    PYTHON = "python"
    MPI = "mpi"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


class ExecutorHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    BUSY = "BUSY"
    UNAVAILABLE = "UNAVAILABLE"


class JobCreateRequest(BaseModel):
    """Payload for POST /api/v1/jobs."""
    job_type: JobType = Field(default=JobType.PYTHON)
    source_code: str = Field(..., max_length=65536)  # max 64 KB
    timeout_sec: int = Field(default=10, ge=1, le=30)
    num_ranks: Optional[int] = Field(default=None, ge=1, le=4)
    cache: bool = Field(default=False)
    tags: Optional[List[str]] = Field(default=None)


class JobSubmitResponse(BaseModel):
    """Response for 202 Accepted or 200 OK (from cache) on POST /api/v1/jobs."""
    job_id: str
    status: JobStatus
    links: Dict[str, str]
    from_cache: bool = False
    result: Optional[Dict[str, Any]] = None


class JobMetadata(BaseModel):
    """Job metadata stored in SQLite scheduler registry."""
    job_id: str
    job_type: str
    source_code: str
    timeout_sec: int
    num_ranks: Optional[int] = None
    cache: bool = False
    tags: List[str] = Field(default_factory=list)
    status: JobStatus = JobStatus.QUEUED
    executor_id: Optional[str] = None
    result_key: Optional[str] = None
    queued_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[float] = None
    failure_reason: Optional[str] = None
    attempts: int = 0
    exit_code: Optional[int] = None
    preview: Optional[str] = None
    truncated: bool = False


class FullExecutionResult(BaseModel):
    """Full execution output stored in Chord DHT."""
    job_id: str
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: float
    sha256: str


class ExecuteCodeParams(BaseModel):
    """Parameters for RPC executeCode."""
    job_id: str
    job_type: JobType
    source_code: str
    timeout_sec: int = 10
    num_ranks: Optional[int] = None
    tags: Optional[List[str]] = None


class ExecuteCodeResult(BaseModel):
    """Result for RPC executeCode."""
    job_id: str
    status: JobStatus
    exit_code: int
    duration_ms: float
    result_key: str
    preview: str
    truncated: bool = False


class ExecutorAttributes(BaseModel):
    """Attribute-based naming metadata for executors."""
    language: str = "python"
    mpi: bool = True
    max_ranks: int = 4
    cpu_cores: int = 4
    memory_mb: int = 256


class PingResult(BaseModel):
    """Result for RPC ping."""
    executor_id: str
    status: ExecutorHealthStatus
    running_jobs: int
    capacity: int
    attributes: Dict[str, Any]
    chord_id: int


class NodeRef(BaseModel):
    """Reference to a node in the Chord ring."""
    node_id: int
    address: str


class FindSuccessorResult(BaseModel):
    """Chord lookup response with hop metrics and path tracing."""
    node_id: int
    address: str
    hops: int = 0
    path: List[int] = Field(default_factory=list)


class InvertedIndexEntry(BaseModel):
    """Inverted index mapping keyword to job IDs in DHT."""
    keyword: str
    job_ids: List[str] = Field(default_factory=list)

