"""REST API router for RemoteLab Scheduler (prefix /api/v1)."""

import asyncio
from datetime import datetime, timezone
import hashlib
import time
from typing import Any, Dict, List, Optional
import uuid

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from common.hashing import chord_hash, compute_cache_key, sha256_hash
from common.models import (
    FullExecutionResult,
    JobCreateRequest,
    JobMetadata,
    JobStatus,
    JobSubmitResponse,
)
from scheduler.cache import SchedulerEdgeCache
from scheduler.db import SchedulerDB
from scheduler.dht_client import DHTClient
from scheduler.registry import ExecutorRegistry
from scheduler.rpc_client import SchedulerRPCClient

router = APIRouter(prefix="/api/v1")


def get_components(request: Request) -> tuple[SchedulerDB, ExecutorRegistry, SchedulerRPCClient, SchedulerEdgeCache, DHTClient]:
    app = request.app
    if not hasattr(app.state, "db"):
        from common.config import SchedulerConfig
        config = SchedulerConfig()
        app.state.db = SchedulerDB(config.db_path)
        app.state.registry = ExecutorRegistry(scheduling_policy=config.scheduling_policy)
        app.state.rpc_client = SchedulerRPCClient(connect_timeout_sec=2.0)
        app.state.edge_cache = SchedulerEdgeCache(capacity=config.cache_capacity, lease_sec=config.cache_lease_sec)
        app.state.dht_client = DHTClient(app.state.registry, app.state.rpc_client)

    return (
        request.app.state.db,
        request.app.state.registry,
        request.app.state.rpc_client,
        request.app.state.edge_cache,
        request.app.state.dht_client,
    )


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED)
async def submit_job(
    job_req: JobCreateRequest,
    request: Request,
    response: Response,
) -> Any:
    """Submit a new job for asynchronous distributed execution, or retrieve cached result."""
    db, registry, rpc_client, edge_cache, dht_client = get_components(request)

    # 1. Deterministic Result Cache check if opt-in cache=True
    if job_req.cache:
        det_key = compute_cache_key(job_req.job_type.value, job_req.source_code, job_req.num_ranks, job_req.timeout_sec)
        cached_val, etag, needs_validation = edge_cache.get(det_key)

        if cached_val is not None:
            if not needs_validation:
                # Valid lease: serve directly < 100 ms
                response.status_code = status.HTTP_200_OK
                return {
                    "job_id": cached_val["job_id"],
                    "status": cached_val["status"],
                    "from_cache": True,
                    "links": {"self": f"/api/v1/jobs/{cached_val['job_id']}"},
                    "result": cached_val,
                }
            else:
                # Expired lease: Check-on-Use validation
                existing_meta = db.get_job(cached_val["job_id"])
                if existing_meta and existing_meta.status == JobStatus.SUCCESS:
                    edge_cache.renew_lease(det_key)
                    response.status_code = status.HTTP_200_OK
                    return {
                        "job_id": cached_val["job_id"],
                        "status": cached_val["status"],
                        "from_cache": True,
                        "links": {"self": f"/api/v1/jobs/{cached_val['job_id']}"},
                        "result": cached_val,
                    }
                else:
                    # Invalidate stale cache
                    edge_cache.invalidate_key(det_key)

    # 2. Enqueue fresh job
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    meta = JobMetadata(
        job_id=job_id,
        job_type=job_req.job_type.value,
        source_code=job_req.source_code,
        timeout_sec=job_req.timeout_sec,
        num_ranks=job_req.num_ranks,
        cache=job_req.cache,
        tags=job_req.tags or [],
        status=JobStatus.QUEUED,
        queued_at=now,
    )
    db.create_job(meta)

    return JobSubmitResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        links={"self": f"/api/v1/jobs/{job_id}"},
        from_cache=False,
    )


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    request: Request,
    response: Response,
    if_none_match: Optional[str] = Header(default=None),
) -> Any:
    """Retrieve job metadata and full output with ETag and 304 Not Modified caching support."""
    db, registry, rpc_client, edge_cache, dht_client = get_components(request)

    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    cache_key = f"job:{job_id}"
    etag = sha256_hash(f"{job.job_id}:{job.finished_at}:{job.status.value}")
    response.headers["ETag"] = f'"{etag}"'
    if job.finished_at:
        response.headers["Last-Modified"] = job.finished_at

    # Conditional GET support: 304 Not Modified
    if if_none_match and if_none_match.strip('"') == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED)

    # If job is final, check Edge Cache with Lease
    if job.status in [JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.TIMEOUT, JobStatus.CANCELLED]:
        cached_result, c_etag, needs_validation = edge_cache.get(cache_key)
        if cached_result is not None and not needs_validation:
            return cached_result

    # Retrieve full output from Chord DHT if available
    full_output = None
    result_available = False
    if job.status in [JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.TIMEOUT]:
        try:
            # Look up job:{job_id} or result_key in Chord ring with strict timeout
            raw_dht = await asyncio.wait_for(dht_client.get_value(f"job:{job_id}"), timeout=1.0)
            if not raw_dht and job.result_key:
                raw_dht = await asyncio.wait_for(dht_client.get_value(job.result_key), timeout=1.0)
            if raw_dht:
                full_output = raw_dht
                result_available = True
        except Exception:
            pass

    payload = {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "status": job.status.value,
        "source_code": job.source_code,
        "num_ranks": job.num_ranks,
        "executor_id": job.executor_id,
        "result_key": job.result_key,
        "queued_at": job.queued_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "duration_ms": job.duration_ms,
        "failure_reason": job.failure_reason,
        "attempts": job.attempts,
        "exit_code": job.exit_code,
        "preview": job.preview,
        "truncated": job.truncated,
        "tags": job.tags,
        "result_available": result_available,
        "full_result": full_output,
    }

    if job.status in [JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.TIMEOUT, JobStatus.CANCELLED]:
        edge_cache.put(cache_key, payload, etag, associated_job_ids=[job.job_id])

    return payload


@router.get("/jobs")
async def list_jobs(
    request: Request,
    status_filter: Optional[str] = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """List jobs with pagination and status filtering."""
    db, _, _, _, _ = get_components(request)
    total = db.count_jobs(status=status_filter)
    jobs = db.list_jobs(status=status_filter, limit=limit, offset=offset)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "jobs": [j.model_dump() for j in jobs],
    }


@router.get("/search")
async def search_jobs(
    request: Request,
    q: str = Query(..., min_length=1),
) -> Dict[str, Any]:
    """Tokenize query and search jobs across Chord inverted index and tags with edge caching."""
    db, _, _, edge_cache, dht_client = get_components(request)
    cache_key = f"search:{q.strip().lower()}"

    # Check Edge Cache
    cached_val, etag, needs_val = edge_cache.get(cache_key)
    if cached_val is not None and not needs_val:
        return cached_val

    # Query Chord DHT inverted index
    matching_ids = await dht_client.search_keywords(q)

    # Also search SQLite tags for exact match
    clean_q = q.strip().lower()
    all_jobs = db.list_jobs(limit=100)
    for j in all_jobs:
        if clean_q in [t.lower() for t in j.tags] and j.job_id not in matching_ids:
            matching_ids.append(j.job_id)

    results = []
    for jid in matching_ids:
        job = db.get_job(jid)
        if job:
            results.append({
                "job_id": job.job_id,
                "status": job.status.value,
                "job_type": job.job_type,
                "preview": job.preview,
                "tags": job.tags,
                "finished_at": job.finished_at,
            })

    response_payload = {
        "query": q,
        "count": len(results),
        "matches": results,
    }
    etag = sha256_hash(f"{q}:{len(results)}")
    edge_cache.put(cache_key, response_payload, etag, associated_job_ids=matching_ids)

    return response_payload


@router.delete("/jobs/{job_id}")
async def cancel_or_delete_job(
    job_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Cancel a queued/running job or invalidate and delete a final job."""
    db, registry, rpc_client, edge_cache, dht_client = get_components(request)

    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.status == JobStatus.QUEUED:
        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.now(timezone.utc).isoformat()
        db.update_job(job)
        edge_cache.invalidate_job(job_id)
        return {"job_id": job_id, "status": JobStatus.CANCELLED.value, "cancelled": True}

    elif job.status == JobStatus.RUNNING:
        # Cancel on executor if known
        if job.executor_id:
            rec = registry.get(job.executor_id)
            if rec:
                try:
                    await rpc_client.cancel_job(rec.url, job_id)
                except Exception:
                    pass
        job.status = JobStatus.CANCELLED
        job.finished_at = datetime.now(timezone.utc).isoformat()
        db.update_job(job)
        edge_cache.invalidate_job(job_id)
        return {"job_id": job_id, "status": JobStatus.CANCELLED.value, "cancelled": True}

    elif job.status in [JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.TIMEOUT]:
        # Invalidate edge cache callbacks (including search and result cache)
        edge_cache.invalidate_job(job_id)
        db.delete_job(job_id)
        return {"job_id": job_id, "deleted": True}

    elif job.status == JobStatus.CANCELLED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job already cancelled")

    raise HTTPException(status_code=400, detail="Invalid job state for deletion")


@router.get("/executors")
async def list_executors(request: Request) -> Dict[str, Any]:
    """Return all registered executors, status, capacity, load, chord ID, and attributes."""
    _, registry, _, _, _ = get_components(request)
    records = registry.list_all()
    return {
        "count": len(records),
        "executors": [r.model_dump() for r in records],
    }


@router.post("/executors/register")
async def register_executor(
    payload: Dict[str, Any],
    request: Request,
) -> Dict[str, Any]:
    """Runtime registration of an executor node."""
    _, registry, _, _, _ = get_components(request)
    eid = payload.get("executor_id")
    url = payload.get("url")
    if not eid or not url:
        raise HTTPException(status_code=400, detail="Missing executor_id or url")

    rec = registry.register(
        executor_id=eid,
        url=url,
        capacity=payload.get("capacity", 2),
        attributes=payload.get("attributes"),
        chord_id=chord_hash(url),
    )
    return {"registered": True, "executor": rec.model_dump()}


@router.get("/dht/lookup")
async def dht_lookup(
    key: str = Query(...),
    request: Request = None,
) -> Dict[str, Any]:
    """Inspect Chord lookup path and hops for a given key string."""
    _, _, _, _, dht_client = get_components(request)
    res = await dht_client.lookup_key(key)
    if not res:
        raise HTTPException(status_code=503, detail="No active Chord DHT node reachable")

    return {
        "key": key,
        "key_chord_id": chord_hash(key),
        "successor_node_id": res.node_id,
        "successor_address": res.address,
        "hops": res.hops,
        "lookup_path": res.path,
    }


@router.get("/health")
async def health_status(request: Request) -> Dict[str, Any]:
    """Return scheduler health, queue backlog, and edge cache hit/miss statistics."""
    db, registry, _, edge_cache, _ = get_components(request)
    queued_count = db.count_jobs(status=JobStatus.QUEUED.value)
    running_count = db.count_jobs(status=JobStatus.RUNNING.value)
    executors = registry.list_all()
    healthy_executors = [e for e in executors if e.status.value == "HEALTHY"]

    return {
        "status": "HEALTHY" if healthy_executors else "DEGRADED",
        "queue": {
            "queued_jobs": queued_count,
            "running_jobs": running_count,
        },
        "executors": {
            "total": len(executors),
            "healthy": len(healthy_executors),
        },
        "cache": edge_cache.stats(),
    }
