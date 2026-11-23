"""Tests for common/lru.py and scheduler/cache.py (Lease, Check-on-Use, Invalidation, Stack Property)."""

import time
import pytest
from common.lru import LRUCache, verify_stack_property
from scheduler.cache import SchedulerEdgeCache


def test_lru_basic_operations():
    cache: LRUCache[str, int] = LRUCache(capacity=3)
    assert len(cache) == 0
    assert cache.get("a") is None
    assert cache.stats()["misses"] == 1
    assert cache.stats()["hits"] == 0

    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert len(cache) == 3

    assert cache.get("a") == 1
    assert cache.stats()["hits"] == 1

    # Accessing "a" makes it MRU. Next put should evict "b" (since order was b, c, a)
    evicted = cache.put("d", 4)
    assert evicted == ("b", 2)
    assert cache.stats()["evictions"] == 1
    assert "b" not in cache
    assert cache.get("b") is None
    assert cache.get("c") == 3
    assert cache.get("a") == 1
    assert cache.get("d") == 4


def test_lru_delete_and_clear():
    cache: LRUCache[str, str] = LRUCache(capacity=2)
    cache.put("x", "1")
    cache.put("y", "2")
    assert cache.delete("x") is True
    assert cache.delete("x") is False
    assert len(cache) == 1

    cache.clear()
    assert len(cache) == 0
    assert cache.stats()["hits"] == 0
    assert cache.stats()["evictions"] == 0


def test_lru_stack_property():
    """Verify Mattson's Stack Property."""
    trace = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5, 1, 3, 2, 4, 1, 5, 2]
    assert verify_stack_property(trace, c1=2, c2=3) is True
    assert verify_stack_property(trace, c1=3, c2=4) is True
    assert verify_stack_property(trace, c1=2, c2=5) is True


def test_edge_cache_lease_and_check_on_use():
    # Cache with 0.2 second lease
    edge_cache = SchedulerEdgeCache(capacity=50, lease_sec=0.2)
    key = "job:test-1"
    payload = {"status": "SUCCESS", "exit_code": 0}
    edge_cache.put(key, payload, etag="etag-123", associated_job_ids=["test-1"])

    # 1. During lease: serve directly without validation
    start = time.perf_counter()
    val, etag, needs_val = edge_cache.get(key)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert val == payload
    assert etag == "etag-123"
    assert needs_val is False
    assert elapsed_ms < 100.0, f"Cache hit response time {elapsed_ms:.2f}ms exceeded 100ms"

    # 2. Wait for lease to expire
    time.sleep(0.25)

    # 3. After expiry: Check-on-Use triggered (needs_val is True)
    val2, etag2, needs_val2 = edge_cache.get(key)
    assert val2 == payload
    assert needs_val2 is True
    assert edge_cache.stats()["check_on_use_validations"] >= 1

    # 4. Renew lease
    edge_cache.renew_lease(key)
    val3, _, needs_val3 = edge_cache.get(key)
    assert needs_val3 is False


def test_edge_cache_callback_invalidation():
    edge_cache = SchedulerEdgeCache(capacity=50, lease_sec=30.0)
    job_id = "job-target-99"

    # Put job entry
    edge_cache.put(f"job:{job_id}", {"data": 1}, "etag-1", associated_job_ids=[job_id])
    # Put search entry that includes this job
    edge_cache.put("search:parallel", {"matches": [{"job_id": job_id}]}, "etag-2", associated_job_ids=[job_id])
    # Put unrelated search entry
    edge_cache.put("search:unrelated", {"matches": []}, "etag-3", associated_job_ids=["other-id"])

    # Verify both present
    assert edge_cache.get(f"job:{job_id}")[0] is not None
    assert edge_cache.get("search:parallel")[0] is not None
    assert edge_cache.get("search:unrelated")[0] is not None

    # Invalidate job_id (callback from DELETE /jobs/{id})
    invalidated_count = edge_cache.invalidate_job(job_id)
    assert invalidated_count >= 2

    # Verify job entry and search:parallel are evicted, while unrelated remains
    assert edge_cache.get(f"job:{job_id}")[0] is None
    assert edge_cache.get("search:parallel")[0] is None
    assert edge_cache.get("search:unrelated")[0] is not None
