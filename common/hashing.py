"""Hashing utilities for Chord DHT and deterministic cache keys."""

import hashlib
from typing import Optional


def chord_hash(key: str, m: int = 32) -> int:
    """Hash a key string into a Chord identifier in range [0, 2^m - 1] using SHA-1."""
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    # Take 4 bytes (32-bit integer)
    val = int.from_bytes(digest[:4], byteorder="big", signed=False)
    if m == 32:
        return val
    return val % (1 << m)


def in_interval_right_closed(val: int, start: int, end: int, m: int = 32) -> bool:
    """Return True if val is in the circular interval (start, end] modulo 2^m."""
    mod = 1 << m
    val = val % mod
    start = start % mod
    end = end % mod

    if start == end:
        # Full ring: any value belongs
        return True
    if start < end:
        return start < val <= end
    else:
        return val > start or val <= end


def in_interval_left_closed(val: int, start: int, end: int, m: int = 32) -> bool:
    """Return True if val is in the circular interval [start, end) modulo 2^m."""
    mod = 1 << m
    val = val % mod
    start = start % mod
    end = end % mod

    if start == end:
        return True
    if start < end:
        return start <= val < end
    else:
        return val >= start or val < end


def in_interval_open(val: int, start: int, end: int, m: int = 32) -> bool:
    """Return True if val is in circular interval (start, end) modulo 2^m."""
    mod = 1 << m
    val = val % mod
    start = start % mod
    end = end % mod

    if start == end:
        return val != start
    if start < end:
        return start < val < end
    else:
        return val > start or val < end


def sha256_hash(data: str | bytes) -> str:
    """Compute standard SHA-256 hex digest for verification or cache keys."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def compute_cache_key(
    job_type: str,
    source_code: str,
    num_ranks: Optional[int],
    timeout_sec: int,
) -> str:
    """Compute deterministic cache key for executeCode caching."""
    payload = f"{job_type}:{num_ranks or 1}:{timeout_sec}:{source_code}"
    return sha256_hash(payload)

