"""Local key-value and replica store with local LRU caching for Chord DHT."""

import threading
from typing import Any, Dict, List, Optional, Set
from common.hashing import chord_hash, in_interval_right_closed
from common.lru import LRUCache


class ChordStore:
    """Thread-safe in-memory store for Chord key-value data with an LRU cache."""

    def __init__(self, cache_capacity: int = 50, m: int = 32):
        self.m = m
        self._lock = threading.Lock()
        self._primary_store: Dict[str, Any] = {}
        self._replica_store: Dict[str, Any] = {}
        self._inverted_index: Dict[str, Set[str]] = {}
        self._local_cache: LRUCache[str, Any] = LRUCache(capacity=cache_capacity)

    def put(self, key: str, value: Any, is_replica: bool = False) -> None:
        """Store key-value pair. Invalidates local LRU cache entry."""
        with self._lock:
            target = self._replica_store if is_replica else self._primary_store
            target[key] = value
            self._local_cache.delete(key)

    def get(self, key: str) -> Optional[Any]:
        """Retrieve key-value pair, checking local LRU cache first, then primary, then replica."""
        with self._lock:
            # Check worker local cache
            cached = self._local_cache.get(key)
            if cached is not None:
                return cached

            # Check primary
            if key in self._primary_store:
                val = self._primary_store[key]
                self._local_cache.put(key, val)
                return val

            # Check replica
            if key in self._replica_store:
                val = self._replica_store[key]
                self._local_cache.put(key, val)
                return val

            return None

    def delete(self, key: str) -> bool:
        """Delete key from primary, replica, and cache."""
        with self._lock:
            self._local_cache.delete(key)
            removed = False
            if key in self._primary_store:
                del self._primary_store[key]
                removed = True
            if key in self._replica_store:
                del self._replica_store[key]
                removed = True
            return removed

    def add_inverted_index(self, keyword: str, job_ids: List[str]) -> None:
        """Thread-safe merge of job IDs for an inverted index keyword."""
        with self._lock:
            if keyword not in self._inverted_index:
                self._inverted_index[keyword] = set()
            self._inverted_index[keyword].update(job_ids)
            # Store representation in primary store as list
            self._primary_store[keyword] = list(self._inverted_index[keyword])
            self._local_cache.delete(keyword)

    def get_inverted_index(self, keyword: str) -> List[str]:
        """Get list of job IDs associated with a keyword."""
        val = self.get(keyword)
        if isinstance(val, list):
            return val
        if isinstance(val, set):
            return list(val)
        return []

    def get_keys_in_range(self, start: int, end: int) -> Dict[str, Any]:
        """Extract all primary keys whose hash falls in (start, end] on the ring."""
        with self._lock:
            transferred: Dict[str, Any] = {}
            for k, v in list(self._primary_store.items()):
                k_id = chord_hash(k, self.m)
                if in_interval_right_closed(k_id, start, end, self.m):
                    transferred[k] = v
            return transferred

    def delete_keys_in_range(self, start: int, end: int) -> None:
        """Remove primary keys in (start, end] after transfer."""
        with self._lock:
            to_del = []
            for k in self._primary_store.keys():
                k_id = chord_hash(k, self.m)
                if in_interval_right_closed(k_id, start, end, self.m):
                    to_del.append(k)
            for k in to_del:
                del self._primary_store[k]
                self._local_cache.delete(k)

    def promote_replicas_to_primary(self) -> None:
        """Promote replica store to primary store (e.g. when predecessor fails)."""
        with self._lock:
            for k, v in self._replica_store.items():
                if k not in self._primary_store:
                    self._primary_store[k] = v
            self._replica_store.clear()

    def get_all_primary(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._primary_store)

