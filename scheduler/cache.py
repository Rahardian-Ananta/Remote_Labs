"""Scheduler Edge Cache with Lease management, Check-on-Use validation, and callback invalidation."""

import time
from typing import Any, Dict, List, Optional, Set, Tuple
from common.lru import LRUCache


class CacheEntry:
    """Cache entry wrapper storing value, ETag, lease expiry, and reverse references."""

    def __init__(
        self,
        key: str,
        value: Any,
        etag: str,
        lease_sec: float,
        associated_job_ids: Optional[List[str]] = None,
    ):
        self.key = key
        self.value = value
        self.etag = etag
        self.lease_expires_at = time.time() + lease_sec
        self.associated_job_ids: List[str] = associated_job_ids or []

    def is_lease_valid(self) -> bool:
        return time.time() < self.lease_expires_at

    def renew_lease(self, lease_sec: float) -> None:
        self.lease_expires_at = time.time() + lease_sec


class SchedulerEdgeCache:
    """Edge Cache for GET /jobs/{id}, GET /search, and deterministic result caching with Lease and Check-on-Use."""

    def __init__(self, capacity: int = 100, lease_sec: float = 30.0):
        self.lease_sec = lease_sec
        self._lru: LRUCache[str, CacheEntry] = LRUCache(capacity=capacity)
        # Reverse mapping for fast invalidation: job_id -> set of cache keys
        self._job_to_keys: Dict[str, Set[str]] = {}
        self.check_on_use_count: int = 0

    def get(self, key: str) -> Tuple[Optional[Any], Optional[str], bool]:
        """Lookup an item.

        Returns (value, etag, needs_validation):
        - If not in cache: (None, None, False)
        - If in cache and lease is valid: (value, etag, False) [direct serve < 100ms]
        - If in cache and lease is expired: (value, etag, True) [requires Check-on-Use]
        """
        entry = self._lru.get(key)
        if entry is None:
            return None, None, False

        if entry.is_lease_valid():
            return entry.value, entry.etag, False

        # Lease expired -> Check-on-Use
        self.check_on_use_count += 1
        return entry.value, entry.etag, True

    def put(
        self,
        key: str,
        value: Any,
        etag: str,
        associated_job_ids: Optional[List[str]] = None,
    ) -> None:
        """Store or update cache entry and record job association for callback invalidation."""
        entry = CacheEntry(
            key=key,
            value=value,
            etag=etag,
            lease_sec=self.lease_sec,
            associated_job_ids=associated_job_ids,
        )
        evicted = self._lru.put(key, entry)
        if evicted:
            evicted_key, evicted_entry = evicted
            for jid in evicted_entry.associated_job_ids:
                if jid in self._job_to_keys:
                    self._job_to_keys[jid].discard(evicted_key)

        # Track associations
        if associated_job_ids:
            for jid in associated_job_ids:
                if jid not in self._job_to_keys:
                    self._job_to_keys[jid] = set()
                self._job_to_keys[jid].add(key)

    def renew_lease(self, key: str) -> None:
        """Renew lease after successful Check-on-Use validation."""
        entry = self._lru.peek(key)
        if entry:
            entry.renew_lease(self.lease_sec)

    def invalidate_key(self, key: str) -> None:
        """Remove a specific key."""
        entry = self._lru.peek(key)
        if entry:
            for jid in entry.associated_job_ids:
                if jid in self._job_to_keys:
                    self._job_to_keys[jid].discard(key)
        self._lru.delete(key)

    def invalidate_job(self, job_id: str) -> int:
        """Invalidate all cache entries associated with a job (direct job entry, search results, result cache)."""
        count = 0
        keys_to_remove = set()

        # 1. Direct job keys
        keys_to_remove.add(f"job:{job_id}")

        # 2. Associated search / result keys tracked in reverse index
        if job_id in self._job_to_keys:
            keys_to_remove.update(self._job_to_keys[job_id])
            del self._job_to_keys[job_id]

        # 3. Check any cache entries that mention job_id in value
        for k in self._lru.keys():
            entry = self._lru.peek(k)
            if entry and job_id in entry.associated_job_ids:
                keys_to_remove.add(k)

        for k in keys_to_remove:
            if self._lru.delete(k):
                count += 1

        return count

    def stats(self) -> Dict[str, Any]:
        s = self._lru.stats()
        s["lease_sec"] = self.lease_sec
        s["check_on_use_validations"] = self.check_on_use_count
        return s

