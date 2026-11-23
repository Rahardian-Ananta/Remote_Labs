"""MPI execution runner leveraging mpirun/mpiexec within the sandbox environment."""

import os
import shutil
import sys
from typing import List, Optional

from common.models import JobStatus
from executor.sandbox import SandboxResult, execute_in_sandbox


def find_mpi_executable() -> Optional[str]:
    """Locate mpirun or mpiexec on PATH or standard install paths."""
    for candidate in ["mpirun", "mpiexec"]:
        path = shutil.which(candidate)
        if path:
            return path

    # Check common MS-MPI paths on Windows
    if sys.platform == "win32":
        msmpi_paths = [
            r"C:\Program Files\Microsoft MPI\Bin\mpiexec.exe",
            r"C:\Program Files (x86)\Microsoft MPI\Bin\mpiexec.exe",
        ]
        for p in msmpi_paths:
            if os.path.exists(p):
                return p

    return None


def is_mpi_available() -> bool:
    """Check if MPI launcher executable is present."""
    return find_mpi_executable() is not None


async def execute_mpi_job(
    source_code: str,
    num_ranks: int = 2,
    max_ranks: int = 4,
    timeout_sec: int = 15,
    max_output_bytes: int = 1048576,
    memory_limit_mb: int = 256,
) -> SandboxResult:
    """Execute an MPI Python script within the sandbox."""
    if num_ranks < 1 or num_ranks > max_ranks:
        return SandboxResult(
            status=JobStatus.FAILED,
            exit_code=-1,
            duration_ms=0.0,
            stdout="",
            stderr=f"Invalid num_ranks: {num_ranks}. Must be between 1 and {max_ranks}.",
            truncated=False,
        )

    mpi_exec = find_mpi_executable()
    if not mpi_exec:
        return SandboxResult(
            status=JobStatus.FAILED,
            exit_code=-1,
            duration_ms=0.0,
            stdout="",
            stderr="MPI runtime (mpirun/mpiexec) is not installed on this node.",
            truncated=False,
        )

    # Build mpirun command
    cmd: List[str] = [mpi_exec, "-n", str(num_ranks)]
    # Add --oversubscribe for OpenMPI on Linux
    if sys.platform != "win32":
        cmd.append("--oversubscribe")

    cmd.extend([sys.executable, "-I", "script.py"])

    return await execute_in_sandbox(
        source_code=source_code,
        timeout_sec=timeout_sec,
        max_output_bytes=max_output_bytes,
        memory_limit_mb=memory_limit_mb,
        custom_cmd=cmd,
    )

