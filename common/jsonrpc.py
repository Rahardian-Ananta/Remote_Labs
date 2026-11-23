"""JSON-RPC 2.0 protocol models, error codes, and helpers."""

from typing import Any, Dict, Optional, Union
from pydantic import BaseModel, Field

# Standard JSON-RPC 2.0 Error Codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# Application-Specific Error Codes
EXECUTOR_BUSY = -32001
JOB_NOT_FOUND = -32002
KEY_NOT_FOUND = -32003

ERROR_MESSAGES: Dict[int, str] = {
    PARSE_ERROR: "Parse error",
    INVALID_REQUEST: "Invalid Request",
    METHOD_NOT_FOUND: "Method not found",
    INVALID_PARAMS: "Invalid params",
    INTERNAL_ERROR: "Internal error",
    EXECUTOR_BUSY: "Executor busy: capacity reached",
    JOB_NOT_FOUND: "Job not found",
    KEY_NOT_FOUND: "Key not found in DHT",
}


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Optional[Any] = None


class JSONRPCRequest(BaseModel):
    jsonrpc: str = Field(default="2.0")
    method: str
    params: Optional[Union[Dict[str, Any], list]] = None
    id: Optional[Union[str, int]] = None


class JSONRPCResponse(BaseModel):
    jsonrpc: str = Field(default="2.0")
    result: Optional[Any] = None
    error: Optional[JSONRPCError] = None
    id: Optional[Union[str, int]] = None


def success_response(req_id: Optional[Union[str, int]], result: Any) -> JSONRPCResponse:
    return JSONRPCResponse(jsonrpc="2.0", id=req_id, result=result)


def error_response(
    req_id: Optional[Union[str, int]],
    code: int,
    message: Optional[str] = None,
    data: Optional[Any] = None,
) -> JSONRPCResponse:
    msg = message or ERROR_MESSAGES.get(code, "Unknown error")
    return JSONRPCResponse(
        jsonrpc="2.0",
        id=req_id,
        error=JSONRPCError(code=code, message=msg, data=data),
    )

