"""Executor node entrypoint and FastAPI HTTP application."""

import contextlib
import logging
import os
import sys
from typing import Any, AsyncGenerator, Dict, Optional
from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse

from common.config import ExecutorConfig
from common.hashing import chord_hash
from common.jsonrpc import PARSE_ERROR, error_response
from executor.chord.maintenance import ChordMaintenance
from executor.chord.node import ChordNode
from executor.rpc_server import ExecutorRPCServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("executor.main")

# Global instances
config = ExecutorConfig()
chord_node: Optional[ChordNode] = None
maintenance: Optional[ChordMaintenance] = None
rpc_server: Optional[ExecutorRPCServer] = None


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global chord_node, maintenance, rpc_server
    if config.executor_url:
        my_address = config.executor_url.rstrip("/")
    elif config.host != "0.0.0.0":
        my_address = f"http://{config.host}:{config.port}"
    else:
        my_address = f"http://127.0.0.1:{config.port}"

    logger.info(f"Starting Executor {config.executor_id} on {my_address}...")

    # Initialize Chord Node
    node_id = chord_hash(my_address, config.chord_m)
    chord_node = ChordNode(
        node_id=node_id,
        address=my_address,
        m=config.chord_m,
        replication_factor=config.chord_replication,
    )

    # Initialize RPC Server
    rpc_server = ExecutorRPCServer(
        executor_id=config.executor_id,
        capacity=config.capacity,
        max_ranks=config.max_ranks,
        max_output_bytes=config.max_output_bytes,
        memory_limit_mb=config.memory_limit_mb,
        db_path=config.db_path or None,
        chord_node=chord_node,
    )

    # Attempt to join ring via bootstrap nodes
    joined = False
    for b_node in config.bootstrap_nodes:
        if b_node.rstrip("/") != my_address:
            try:
                success = await chord_node.join(b_node)
                if success:
                    joined = True
                    logger.info(f"Joined Chord ring via {b_node}. Successor is {chord_node.successor.node_id}")
                    break
            except Exception as e:
                logger.debug(f"Could not bootstrap from {b_node}: {e}")

    if not joined:
        logger.info("Initializing as initial independent ring node.")
        await chord_node.join(my_address)

    # Start periodic maintenance
    maintenance = ChordMaintenance(chord_node, interval_sec=config.chord_maintenance_sec)
    maintenance.start()

    yield

    # Shutdown
    logger.info("Shutting down executor node...")
    if maintenance:
        await maintenance.stop()
    if chord_node:
        await chord_node.close()


app = FastAPI(title="RemoteLab Executor Node", lifespan=lifespan)


@app.post("/rpc")
async def rpc_endpoint(
    request: Request,
    x_request_id: Optional[str] = Header(default=None),
) -> JSONResponse:
    """JSON-RPC 2.0 endpoint over HTTP."""
    try:
        body = await request.json()
    except Exception as ex:
        err = error_response(None, PARSE_ERROR, f"Invalid JSON body: {ex}")
        return JSONResponse(status_code=200, content=err.model_dump())

    response = await rpc_server.handle_request(body, request_id=x_request_id)
    return JSONResponse(status_code=200, content=response.model_dump())


@app.get("/health")
async def health_check() -> Dict[str, Any]:
    """Basic health check probe."""
    if not rpc_server:
        return {"status": "INITIALIZING"}
    ping_res = await rpc_server.ping()
    return ping_res.model_dump()


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("EXECUTOR_PORT", str(config.port)))
    uvicorn.run("executor.main:app", host="0.0.0.0", port=port, log_level="info")

