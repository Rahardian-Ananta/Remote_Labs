"""DHT Client for the Scheduler to route queries into the Chord ring."""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Set
from common.hashing import chord_hash
from common.models import FindSuccessorResult
from scheduler.registry import ExecutorRegistry
from scheduler.rpc_client import SchedulerRPCClient

logger = logging.getLogger("scheduler.dht_client")


class DHTClient:
    """Provides DHT lookup, key retrieval, and search capabilities across the Chord ring."""

    def __init__(
        self,
        registry: ExecutorRegistry,
        rpc_client: SchedulerRPCClient,
        m: int = 32,
    ):
        self.registry = registry
        self.rpc_client = rpc_client
        self.m = m

    def _get_healthy_entry_points(self) -> List[str]:
        """Return list of URLs for healthy executor nodes to serve as DHT entry points."""
        executors = self.registry.list_all()
        # Prefer healthy nodes
        healthy = [rec.url for rec in executors if rec.status.value == "HEALTHY"]
        if healthy:
            return healthy
        # Fallback to any registered executor
        return [rec.url for rec in executors]

    async def lookup_key(self, key: str) -> Optional[FindSuccessorResult]:
        """Perform Chord findSuccessor lookup, returning successor node and hop path."""
        key_id = chord_hash(key, self.m)
        entry_points = self._get_healthy_entry_points()
        if not entry_points:
            return None

        for entry in entry_points:
            try:
                res = await self.rpc_client.chord_find_successor(entry, identifier=key_id)
                return res
            except Exception as e:
                logger.debug(f"Lookup via entry point {entry} failed: {e}")
                continue

        return None

    async def get_value(self, key: str) -> Optional[Any]:
        """Look up key in DHT: routes to successor node, then calls chord.get."""
        lookup_res = await self.lookup_key(key)
        if not lookup_res:
            return None

        # 1. Try target node
        try:
            val = await self.rpc_client.chord_get(lookup_res.address, key)
            if val is not None:
                return val
        except Exception as e:
            logger.debug(f"Direct chord.get from {lookup_res.address} failed: {e}")

        # 2. Fallback: try other entry points (which can check replica or internal store)
        for entry in self._get_healthy_entry_points():
            if entry != lookup_res.address:
                try:
                    val = await self.rpc_client.chord_get(entry, key)
                    if val is not None:
                        return val
                except Exception:
                    continue

        return None

    async def search_keywords(self, query: str) -> List[str]:
        """Tokenize search query, query DHT inverted index for each word, and return intersection of job IDs."""
        words = re.findall(r"[a-zA-Z0-9_\-]+", query.lower())
        clean_words = [w for w in words if len(w) >= 2]
        if not clean_words:
            return []

        entry_points = self._get_healthy_entry_points()
        if not entry_points:
            return []

        all_matches_per_word: Dict[str, Set[str]] = {w: set() for w in clean_words}

        async def _query_node(url: str, word: str) -> None:
            try:
                val = await self.rpc_client.chord_get(url, word)
                if val:
                    if isinstance(val, list):
                        all_matches_per_word[word].update(val)
                    elif isinstance(val, set):
                        all_matches_per_word[word].update(val)
            except Exception:
                pass

        tasks = [_query_node(url, w) for url in entry_points for w in clean_words]
        await asyncio.gather(*tasks, return_exceptions=True)

        results: Optional[Set[str]] = None
        for w in clean_words:
            job_set = all_matches_per_word[w]
            if results is None:
                results = set(job_set)
            else:
                results &= job_set

        return sorted(list(results or set()))

