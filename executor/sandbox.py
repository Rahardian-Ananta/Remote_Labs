"""Sandbox execution environment for untrusted Python and MPI scripts."""

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Optional
import psutil

from common.models import JobStatus

# Try importing resource on POSIX
try:
    import resource
except ImportError:
    resource = None


class SandboxResult:
    """Result of sandbox script execution."""
    def __init__(
        self,
        status: JobStatus,
        exit_code: int,
        duration_ms: float,
        stdout: str,
        stderr: str,
        truncated: bool = False,
    ):
        self.status = status
        self.exit_code = exit_code
        self.duration_ms = duration_ms
        self.stdout = stdout
        self.stderr = stderr
        self.truncated = truncated


def _kill_process_tree(pid: int) -> None:
    """Terminate the process and all child processes recursively."""
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        parent.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def _set_posix_limits(memory_limit_mb: int, cpu_limit_sec: int) -> None:
    """Apply POSIX resource limits via resource.setrlimit (preexec_fn)."""
    if resource is None:
        return
    try:
        # RLIMIT_AS (virtual memory)
        mem_bytes = memory_limit_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        # RLIMIT_CPU (CPU time seconds)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_limit_sec + 2, cpu_limit_sec + 2))
        # RLIMIT_FSIZE (max file size 10MB)
        resource.setrlimit(resource.RLIMIT_FSIZE, (10 * 1024 * 1024, 10 * 1024 * 1024))
        # RLIMIT_NOFILE
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    except (ValueError, OSError):
        pass


async def _read_stream_limited(
    stream: asyncio.StreamReader,
    max_bytes: int,
    stop_event: asyncio.Event,
    proc: asyncio.subprocess.Process,
) -> tuple[bytes, bool]:
    """Read stream incrementally up to max_bytes. If exceeded, sets stop_event, kills proc, and returns truncated=True."""
    buffer = bytearray()
    truncated = False
    chunk_size = 4096

    while not stream.at_eof():
        if stop_event.is_set():
            break
        try:
            chunk = await stream.read(chunk_size)
        except Exception:
            break
        if not chunk:
            break

        if len(buffer) + len(chunk) > max_bytes:
            remaining = max_bytes - len(buffer)
            if remaining > 0:
                buffer.extend(chunk[:remaining])
            truncated = True
            stop_event.set()
            _kill_process_tree(proc.pid)
            break
        buffer.extend(chunk)

    return bytes(buffer), truncated


async def execute_in_sandbox(
    source_code: str,
    timeout_sec: int = 10,
    max_output_bytes: int = 1048576,  # 1 MB
    memory_limit_mb: int = 256,
    custom_cmd: Optional[List[str]] = None,
    extra_files: Optional[Dict[str, str]] = None,
    cwd_override: Optional[str] = None,
) -> SandboxResult:
    """Execute code in an isolated temporary directory with timeouts and output bounds."""
    workdir = cwd_override or tempfile.mkdtemp(prefix="remotelab_sandbox_")
    script_path = os.path.join(workdir, "script.py")

    try:
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(source_code)

        if extra_files:
            for fname, content in extra_files.items():
                target_path = os.path.join(workdir, fname)
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                with open(target_path, "w", encoding="utf-8") as ef:
                    ef.write(content)

        # Build command
        if custom_cmd:
            cmd = list(custom_cmd)
        else:
            cmd = [sys.executable, "-I", "script.py"]

        # Minimal sanitized environment
        env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "TEMP": workdir,
            "TMP": workdir,
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
        }

        preexec = None
        creationflags = 0
        if sys.platform != "win32":
            preexec = lambda: _set_posix_limits(memory_limit_mb, timeout_sec)
        else:
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        start_time = time.perf_counter()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=workdir,
            env=env,
            preexec_fn=preexec,
            creationflags=creationflags,
        )

        stop_event = asyncio.Event()

        # Run stream readers concurrently
        stdout_task = asyncio.create_task(_read_stream_limited(proc.stdout, max_output_bytes, stop_event, proc))
        stderr_task = asyncio.create_task(_read_stream_limited(proc.stderr, max_output_bytes, stop_event, proc))

        timed_out = False
        try:
            await asyncio.wait_for(proc.wait(), timeout=float(timeout_sec))
        except asyncio.TimeoutError:
            timed_out = True
            _kill_process_tree(proc.pid)
            try:
                await proc.wait()
            except Exception:
                pass

        # Wait for readers to finish reading available data
        try:
            stdout_bytes, stdout_trunc = await asyncio.wait_for(stdout_task, timeout=2.0)
        except asyncio.TimeoutError:
            stdout_bytes, stdout_trunc = b"", False

        try:
            stderr_bytes, stderr_trunc = await asyncio.wait_for(stderr_task, timeout=2.0)
        except asyncio.TimeoutError:
            stderr_bytes, stderr_trunc = b"", False

        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        truncated = stdout_trunc or stderr_trunc

        stdout_str = stdout_bytes.decode("utf-8", errors="replace")
        stderr_str = stderr_bytes.decode("utf-8", errors="replace")

        if timed_out:
            return SandboxResult(
                status=JobStatus.TIMEOUT,
                exit_code=-1,
                duration_ms=duration_ms,
                stdout=stdout_str,
                stderr=stderr_str or f"Execution timed out after {timeout_sec} seconds",
                truncated=truncated,
            )

        exit_code = proc.returncode if proc.returncode is not None else -1
        status = JobStatus.SUCCESS if exit_code == 0 else JobStatus.FAILED

        return SandboxResult(
            status=status,
            exit_code=exit_code,
            duration_ms=duration_ms,
            stdout=stdout_str,
            stderr=stderr_str,
            truncated=truncated,
        )

    finally:
        if cwd_override is None and os.path.exists(workdir):
            shutil.rmtree(workdir, ignore_errors=True)
