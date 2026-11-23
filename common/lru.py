"""Custom LRU cache implementation backed by collections.OrderedDict with hit/miss/eviction metrics."""

from collections import OrderedDict
from typing import Any, Dict, Generic, List, Optional, Tuple, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LRUCache(Generic[K, V]):
    """Thread-safe-friendly LRU Cache tracking hits, misses, and evictions."""

    def __init__(self, capacity: int = 100):
        if capacity <= 0:
            raise ValueError("Capacity must be greater than 0")
        self.capacity: int = capacity
        self._cache: OrderedDict[K, V] = OrderedDict()
        self.hits: int = 0
        self.misses: int = 0
        self.evictions: int = 0

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Retrieve an item, moving it to the most-recently-used position. Returns default on miss."""
        if key in self._cache:
            self.hits += 1
            self._cache.move_to_end(key, last=True)
            return self._cache[key]
        self.misses += 1
        return default

    def peek(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Look up a value without updating MRU order or incrementing hit/miss stats."""
        return self._cache.get(key, default)

    def put(self, key: K, value: V) -> Optional[Tuple[K, V]]:
        """Insert or update a key. If an eviction occurs, returns (evicted_key, evicted_value)."""
        evicted = None
        if key in self._cache:
            self._cache[key] = value
            self._cache.move_to_end(key, last=True)
            return None

        if len(self._cache) >= self.capacity:
            evicted_key, evicted_val = self._cache.popitem(last=False)
            self.evictions += 1
            evicted = (evicted_key, evicted_val)

        self._cache[key] = value
        return evicted

    def delete(self, key: K) -> bool:
        """Remove a key from the cache. Returns True if existed."""
        if key in self._cache:
            del self._cache[key]
            return True
        return False

    def clear(self) -> None:
        """Clear all entries and reset counters."""
        self._cache.clear()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def __contains__(self, key: K) -> bool:
        return key in self._cache

    def __len__(self) -> int:
        return len(self._cache)

    def keys(self) -> List[K]:
        """Return list of keys from LRU to MRU order."""
        return list(self._cache.keys())

    def values(self) -> List[V]:
        """Return list of values from LRU to MRU order."""
        return list(self._cache.values())

    def stats(self) -> Dict[str, Any]:
        """Return dictionary of cache metrics."""
        total = self.hits + self.misses
        hit_ratio = (self.hits / total) if total > 0 else 0.0
        return {
            "capacity": self.capacity,
            "size": len(self._cache),
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_ratio": round(hit_ratio, 4),
        }


def verify_stack_property(trace: List[K], c1: int, c2: int) -> bool:
    """Verify Mattson's Stack Property: for LRU, if c1 < c2, the contents of cache(c1)

    at any point in time during the trace are a subset of cache(c2).
    """
    assert c1 < c2
    cache1: LRUCache[K, int] = LRUCache(capacity=c1)
    cache2: LRUCache[K, int] = LRUCache(capacity=c2)

    for item in trace:
        cache1.get(item)
        if item not in cache1:
            cache1.put(item, 1)

        cache2.get(item)
        if item not in cache2:
            cache2.put(item, 1)

        # Check subset: all keys in cache1 must be in cache2
        set1 = set(cache1.keys())
        set2 = set(cache2.keys())
        if not set1.issubset(set2):
            return False

    # Also, hit count of cache2 must be >= hit count of cache1
    return cache2.hits >= cache1.hits

