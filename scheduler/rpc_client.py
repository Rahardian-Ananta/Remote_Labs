"""RPC Client Stub for invoking Executor nodes over JSON-RPC 2.0 HTTP."""

import logging
import uuid
from typing import Any, Dict, List, Optional
import httpx

from common.jsonrpc import JSONRPCResponse
from common.models import (
    ExecuteCodeResult,
    FindSuccessorResult,
    JobStatus,
    JobType,
    PingResult,
)

logger = logging.getLogger("scheduler.rpc_client")


class RPCClientError(Exception):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(f"RPC Error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class SchedulerRPCClient:
    """Async Client Stub providing access transparency to remote executors."""

    def __init__(self, connect_timeout_sec: float = 5.0):
        self.connect_timeout_sec = connect_timeout_sec
        self._client: Optional[httpx.AsyncClient] = None

    def get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
            self._client = httpx.AsyncClient(limits=limits)
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _post(
        self,
        executor_url: str,
        method: str,
        params: Dict[str, Any],
        read_timeout_sec: float = 10.0,
        connect_timeout_override: Optional[float] = None,
        request_id: Optional[str] = None,
    ) -> Any:
        req_id = request_id or str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": req_id,
        }
        url = f"{executor_url.rstrip('/')}/rpc"
        conn_timeout = connect_timeout_override or self.connect_timeout_sec
        timeout = httpx.Timeout(read_timeout_sec, connect=conn_timeout)

        client = self.get_client()
        resp = await client.post(url, json=payload, headers={"X-Request-Id": req_id}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data and data["error"]:
            err = data["error"]
            raise RPCClientError(code=err.get("code", -32603), message=err.get("message", "Error"), data=err.get("data"))
        return data.get("result")

    async def ping(self, executor_url: str, request_id: Optional[str] = None) -> PingResult:
        res = await self._post(executor_url, "ping", {}, read_timeout_sec=2.0, connect_timeout_override=1.0, request_id=request_id)
        return PingResult(**res)

    async def execute_code(
        self,
        executor_url: str,
        job_id: str,
        job_type: str,
        source_code: str,
        timeout_sec: int = 10,
        num_ranks: Optional[int] = None,
        tags: Optional[List[str]] = None,
        request_id: Optional[str] = None,
    ) -> ExecuteCodeResult:
        params = {
            "job_id": job_id,
            "job_type": job_type,
            "source_code": source_code,
            "timeout_sec": timeout_sec,
            "num_ranks": num_ranks,
            "tags": tags or [],
        }
        # Read timeout = timeout_sec + 5s
        res = await self._post(
            executor_url,
            "executeCode",
            params,
            read_timeout_sec=float(timeout_sec) + 5.0,
            request_id=request_id,
        )
        return ExecuteCodeResult(**res)

    async def get_status(self, executor_url: str, job_id: str, request_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            return await self._post(executor_url, "getStatus", {"job_id": job_id}, read_timeout_sec=4.0, request_id=request_id)
        except RPCClientError as e:
            if e.code == -32002:  # JOB_NOT_FOUND
                return None
            raise

    async def cancel_job(self, executor_url: str, job_id: str, request_id: Optional[str] = None) -> bool:
        res = await self._post(executor_url, "cancelJob", {"job_id": job_id}, read_timeout_sec=4.0, request_id=request_id)
        return bool(res.get("cancelled", False))

    async def chord_find_successor(
        self,
        executor_url: str,
        identifier: int,
        hops: int = 0,
        path: Optional[List[int]] = None,
        request_id: Optional[str] = None,
    ) -> FindSuccessorResult:
        params = {"id": identifier, "hops": hops, "path": path or []}
        res = await self._post(executor_url, "chord.findSuccessor", params, read_timeout_sec=5.0, request_id=request_id)
        return FindSuccessorResult(**res)

    async def chord_get(self, executor_url: str, key: str, request_id: Optional[str] = None) -> Optional[Any]:
        return await self._post(executor_url, "chord.get", {"key": key}, read_timeout_sec=5.0, request_id=request_id)

    async def chord_put(self, executor_url: str, key: str, value: Any, replicate: bool = True, request_id: Optional[str] = None) -> bool:
        res = await self._post(executor_url, "chord.put", {"key": key, "value": value, "replicate": replicate}, read_timeout_sec=5.0, request_id=request_id)
        return bool(res)

    async def chord_delete(self, executor_url: str, key: str, request_id: Optional[str] = None) -> bool:
        res = await self._post(executor_url, "chord.delete", {"key": key}, read_timeout_sec=5.0, request_id=request_id)
        return bool(res)

