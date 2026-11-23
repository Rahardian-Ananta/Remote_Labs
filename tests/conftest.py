"""Pytest fixtures for launching real uvicorn processes for Scheduler and Executors."""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Dict, Generator, List, Optional
import httpx
import psutil
import pytest


def get_free_port() -> int:
    """Find an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get_short_path(long_path: str) -> str:
    """On Windows, return the 8.3 short path to avoid Unicode issues in subprocess env.
    On non-Windows, returns the path unchanged.
    """
    if sys.platform != "win32":
        return long_path
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(512)
        get_short = ctypes.windll.kernel32.GetShortPathNameW
        ret = get_short(long_path, buf, 512)
        if ret and buf.value:
            return buf.value
    except Exception:
        pass
    return long_path


# Resolve the remotelab project root as a short path to handle non-ASCII directories
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT_LONG = os.path.abspath(os.path.join(_TESTS_DIR, ".."))
_PROJECT_ROOT_SHORT = _get_short_path(_PROJECT_ROOT_LONG)

# Use the venv Python (short path) so subprocess can find it even in Unicode dirs
_VENV_PYTHON = _get_short_path(sys.executable)


class ManagedServer:
    """Wrapper managing a live uvicorn process with health polling and clean teardown."""

    def __init__(self, name: str, app_module: str, port: int, env: Dict[str, str], health_path: str = "/health"):
        self.name = name
        self.app_module = app_module
        self.port = port
        self.env = env
        self.health_path = health_path
        self.process: Optional[subprocess.Popen] = None
        self.url = f"http://127.0.0.1:{port}"

    def start(self, timeout_sec: float = 30.0) -> None:
        """Start the uvicorn subprocess and poll until responsive."""
        full_env = os.environ.copy()
        full_env.update(self.env)
        # Ensure python unbuffered and UTF-8 mode (important for Windows with non-ASCII paths)
        full_env["PYTHONUNBUFFERED"] = "1"
        full_env["PYTHONUTF8"] = "1"
        full_env["PYTHONPATH"] = _PROJECT_ROOT_SHORT

        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        cmd = [
            _VENV_PYTHON,
            "-m",
            "uvicorn",
            self.app_module,
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--log-level",
            "warning",
        ]
        self._stderr_file = open(os.path.join(tempfile.gettempdir(), f"remotelab_{self.name}_{self.port}_stderr.log"), "w+", encoding="utf-8")
        self.process = subprocess.Popen(
            cmd,
            env=full_env,
            cwd=_PROJECT_ROOT_SHORT,
            stdout=subprocess.DEVNULL,
            stderr=self._stderr_file,
            creationflags=creationflags,
        )

        # Poll health endpoint until online
        start = time.time()
        client = httpx.Client(timeout=1.0)
        while time.time() - start < timeout_sec:
            if self.process.poll() is not None:
                self._stderr_file.flush()
                self._stderr_file.seek(0)
                err_content = self._stderr_file.read()[-2000:]
                self._stderr_file.close()
                raise RuntimeError(
                    f"Server {self.name} exited prematurely with code {self.process.returncode}\nStderr:\n{err_content}"
                )
            try:
                r = client.get(f"{self.url}{self.health_path}")
                if r.status_code == 200:
                    client.close()
                    return
            except Exception:
                time.sleep(0.2)
        client.close()
        self._stderr_file.flush()
        self._stderr_file.seek(0)
        last_stderr = self._stderr_file.read()[-2000:]
        self.stop()
        raise TimeoutError(f"Server {self.name} failed to become healthy within {timeout_sec}s. Stderr:\n{last_stderr}")

    def stop(self) -> None:
        """Terminate the server process and all children cleanly."""
        if hasattr(self, "_stderr_file") and self._stderr_file and not self._stderr_file.closed:
            try:
                self._stderr_file.close()
            except Exception:
                pass
        if self.process and self.process.poll() is None:
            try:
                parent = psutil.Process(self.process.pid)
                for child in parent.children(recursive=True):
                    try:
                        child.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                parent.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            try:
                self.process.wait(timeout=2.0)
            except Exception:
                pass
        self.process = None


class TestCluster:
    """Represents a full multi-node RemoteLab cluster."""

    def __init__(self, scheduler: ManagedServer, executors: Dict[str, ManagedServer], temp_dir: str):
        self.scheduler = scheduler
        self.executors = executors
        self.temp_dir = temp_dir

    def stop_executor(self, eid: str) -> None:
        if eid in self.executors:
            self.executors[eid].stop()

    def start_executor(self, eid: str) -> None:
        if eid in self.executors:
            self.executors[eid].start()

    def teardown(self) -> None:
        for ex in self.executors.values():
            ex.stop()
        self.scheduler.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)


@pytest.fixture(scope="function")
def cluster() -> Generator[TestCluster, None, None]:
    """Spins up 1 real scheduler and 3 real executors on dynamic free ports."""
    temp_dir = tempfile.mkdtemp(prefix="remotelab_test_cluster_")

    e1_port = get_free_port()
    e2_port = get_free_port()
    e3_port = get_free_port()
    s_port = get_free_port()

    e1_url = f"http://127.0.0.1:{e1_port}"
    e2_url = f"http://127.0.0.1:{e2_port}"
    e3_url = f"http://127.0.0.1:{e3_port}"

    bootstraps = f"{e1_url},{e2_url},{e3_url}"

    executors_env = f"exec1={e1_url},exec2={e2_url},exec3={e3_url}"

    # Build Executor 1
    e1 = ManagedServer(
        name="exec1",
        app_module="executor.main:app",
        port=e1_port,
        env={
            "EXECUTOR_ID": "exec1",
            "EXECUTOR_HOST": "127.0.0.1",
            "EXECUTOR_PORT": str(e1_port),
            "EXECUTOR_CAPACITY": "2",
            "MAX_RANKS": "4",
            "EXECUTOR_DB_PATH": os.path.join(temp_dir, "exec1.db"),
            "BOOTSTRAP_NODES": bootstraps,
            "CHORD_MAINTENANCE_SEC": "1.5",
        },
    )

    # Build Executor 2
    e2 = ManagedServer(
        name="exec2",
        app_module="executor.main:app",
        port=e2_port,
        env={
            "EXECUTOR_ID": "exec2",
            "EXECUTOR_HOST": "127.0.0.1",
            "EXECUTOR_PORT": str(e2_port),
            "EXECUTOR_CAPACITY": "2",
            "MAX_RANKS": "4",
            "EXECUTOR_DB_PATH": os.path.join(temp_dir, "exec2.db"),
            "BOOTSTRAP_NODES": bootstraps,
            "CHORD_MAINTENANCE_SEC": "1.5",
        },
    )

    # Build Executor 3
    e3 = ManagedServer(
        name="exec3",
        app_module="executor.main:app",
        port=e3_port,
        env={
            "EXECUTOR_ID": "exec3",
            "EXECUTOR_HOST": "127.0.0.1",
            "EXECUTOR_PORT": str(e3_port),
            "EXECUTOR_CAPACITY": "2",
            "MAX_RANKS": "4",
            "EXECUTOR_DB_PATH": os.path.join(temp_dir, "exec3.db"),
            "BOOTSTRAP_NODES": bootstraps,
            "CHORD_MAINTENANCE_SEC": "1.5",
        },
    )

    # Start executors first so ring forms
    e1.start()
    e2.start()
    e3.start()

    # Build Scheduler
    sched_db = os.path.join(temp_dir, "scheduler.db")
    sched = ManagedServer(
        name="scheduler",
        app_module="scheduler.main:app",
        port=s_port,
        env={
            "SCHEDULER_HOST": "127.0.0.1",
            "SCHEDULER_PORT": str(s_port),
            "EXECUTORS": executors_env,
            "DB_PATH": sched_db,
            "HEALTH_INTERVAL_SEC": "1.0",
            "CACHE_CAPACITY": "100",
            "CACHE_LEASE_SEC": "30.0",
        },
    )
    sched.start()

    tc = TestCluster(
        scheduler=sched,
        executors={"exec1": e1, "exec2": e2, "exec3": e3},
        temp_dir=temp_dir,
    )

    yield tc

    tc.teardown()

