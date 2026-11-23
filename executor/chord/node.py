"""Chord DHT Node logic with finger table routing, replication, and self-healing."""

import asyncio
import logging
from typing import Any, Dict, List, Optional
import httpx

from common.hashing import (
    chord_hash,
    in_interval_left_closed,
    in_interval_open,
    in_interval_right_closed,
)
from common.jsonrpc import KEY_NOT_FOUND, JSONRPCRequest, JSONRPCResponse
from common.models import FindSuccessorResult, NodeRef
from executor.chord.store import ChordStore

logger = logging.getLogger("chord.node")


class ChordNode:
    """A simpul (node) within the Chord DHT ring."""

    def __init__(
        self,
        node_id: Optional[int],
        address: str,
        m: int = 32,
        replication_factor: int = 2,
    ):
        self.address = address.rstrip("/")
        self.m = m
        self.replication_factor = replication_factor
        self.node_id = node_id if node_id is not None else chord_hash(self.address, m)

        self.self_ref = NodeRef(node_id=self.node_id, address=self.address)
        self.successor: NodeRef = self.self_ref
        self.predecessor: Optional[NodeRef] = None
        self.successor_list: List[NodeRef] = [self.self_ref, self.self_ref]

        # Finger table FT[i] = succ(n + 2^i) for i = 0..m-1
        self.finger_table: List[NodeRef] = [self.self_ref] * self.m
        self.next_finger: int = 0

        self.store = ChordStore(cache_capacity=50, m=self.m)
        self._http_client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()
        self.network_registry: Optional[Dict[str, "ChordNode"]] = None

    async def get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=3.0)
        return self._http_client

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()

    async def rpc_call(self, target_address: str, method: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Call a JSON-RPC method on a remote Chord node."""
        if target_address.rstrip("/") == self.address:
            # Local dispatch directly
            return await self.dispatch_local_rpc(method, params or {})

        if self.network_registry and target_address.rstrip("/") in self.network_registry:
            target_node = self.network_registry[target_address.rstrip("/")]
            return await target_node.dispatch_local_rpc(method, params or {})

        client = await self.get_http_client()
        req_body = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": f"chord_{self.node_id}_{method}",
        }
        url = f"{target_address.rstrip('/')}/rpc"
        try:
            resp = await client.post(url, json=req_body, headers={"X-Request-Id": f"chord-{self.node_id}"})
            resp.raise_for_status()
            data = resp.json()
            if "error" in data and data["error"]:
                raise RuntimeError(f"RPC Error {data['error'].get('code')}: {data['error'].get('message')}")
            return data.get("result")
        except Exception as e:
            logger.debug(f"RPC call {method} to {target_address} failed: {e}")
            raise

    async def dispatch_local_rpc(self, method: str, params: Dict[str, Any]) -> Any:
        """Dispatch Chord RPC methods locally without HTTP overhead."""
        if method == "chord.findSuccessor":
            key_id = params.get("id")
            hops = params.get("hops", 0)
            path = params.get("path", [])
            res = await self.find_successor(key_id, hops=hops, path=path)
            return res.model_dump()
        elif method == "chord.getPredecessor":
            return self.predecessor.model_dump() if self.predecessor else None
        elif method == "chord.notify":
            node_id = params["node_id"]
            address = params["address"]
            return await self.notify(NodeRef(node_id=node_id, address=address))
        elif method == "chord.getSuccessorList":
            return [nr.model_dump() for nr in self.successor_list]
        elif method == "chord.put":
            return await self.handle_put(params["key"], params["value"], params.get("replicate", True))
        elif method == "chord.get":
            return await self.handle_get(params["key"])
        elif method == "chord.delete":
            return await self.handle_delete(params["key"])
        elif method == "chord.transferKeys":
            return await self.handle_transfer_keys(params["from_id"], params["to_id"])
        else:
            raise ValueError(f"Unknown local method: {method}")

    def closest_preceding_finger(self, identifier: int) -> NodeRef:
        """Find the closest preceding finger for identifier in (n, identifier)."""
        for i in range(self.m - 1, -1, -1):
            f_node = self.finger_table[i]
            if in_interval_open(f_node.node_id, self.node_id, identifier, self.m):
                return f_node
        return self.self_ref

    async def find_successor(
        self,
        identifier: int,
        hops: int = 0,
        path: Optional[List[int]] = None,
    ) -> FindSuccessorResult:
        """Look up successor node for identifier, tracking hops and traversed path."""
        current_path = list(path or [])
        if self.node_id not in current_path:
            current_path.append(self.node_id)

        # Base case 1: only node in the ring
        if self.successor.node_id == self.node_id:
            return FindSuccessorResult(
                node_id=self.node_id,
                address=self.address,
                hops=hops,
                path=current_path,
            )

        # Base case 2: identifier in (n, successor]
        if in_interval_right_closed(identifier, self.node_id, self.successor.node_id, self.m):
            if self.successor.node_id not in current_path:
                current_path.append(self.successor.node_id)
            return FindSuccessorResult(
                node_id=self.successor.node_id,
                address=self.successor.address,
                hops=hops + 1,
                path=current_path,
            )

        # Forward lookup to closest preceding finger
        n_prime = self.closest_preceding_finger(identifier)
        if n_prime.node_id == self.node_id or n_prime.node_id in current_path:
            # Forward directly to successor to prevent infinite cycle
            n_prime = self.successor

        # Cycle / hop limit prevention: if n_prime is already visited or hops exceeded, stop routing
        if n_prime.node_id in current_path or hops >= 16 or len(current_path) >= 16:
            return FindSuccessorResult(
                node_id=self.successor.node_id,
                address=self.successor.address,
                hops=hops + 1,
                path=current_path + ([self.successor.node_id] if self.successor.node_id not in current_path else []),
            )

        try:
            result_data = await self.rpc_call(
                n_prime.address,
                "chord.findSuccessor",
                {"id": identifier, "hops": hops + 1, "path": current_path},
            )
            return FindSuccessorResult(**result_data)
        except Exception:
            # Fall back to next node in successor list if n_prime failed
            for succ in self.successor_list:
                if succ.node_id != self.node_id and succ.node_id != n_prime.node_id:
                    try:
                        result_data = await self.rpc_call(
                            succ.address,
                            "chord.findSuccessor",
                            {"id": identifier, "hops": hops + 1, "path": current_path},
                        )
                        return FindSuccessorResult(**result_data)
                    except Exception:
                        continue

            return FindSuccessorResult(
                node_id=self.successor.node_id,
                address=self.successor.address,
                hops=hops + 1,
                path=current_path + [self.successor.node_id],
            )

    async def join(self, bootstrap_address: str) -> bool:
        """Join an existing Chord ring via bootstrap node address."""
        if bootstrap_address.rstrip("/") == self.address:
            # Bootstrap is ourselves (first node in ring)
            self.predecessor = None
            self.successor = self.self_ref
            self.successor_list = [self.self_ref, self.self_ref]
            self.finger_table = [self.self_ref] * self.m
            return True

        try:
            res_dict = await self.rpc_call(
                bootstrap_address,
                "chord.findSuccessor",
                {"id": self.node_id, "hops": 0, "path": []},
            )
            res = FindSuccessorResult(**res_dict)
            self.successor = NodeRef(node_id=res.node_id, address=res.address)
            self.finger_table[0] = self.successor
            self.successor_list = [self.successor, self.self_ref]

            # Request key transfer from successor
            if self.successor.node_id != self.node_id:
                try:
                    transferred = await self.rpc_call(
                        self.successor.address,
                        "chord.transferKeys",
                        {"from_id": self.node_id, "to_id": self.successor.node_id},
                    )
                    if isinstance(transferred, dict):
                        for k, v in transferred.items():
                            self.store.put(k, v, is_replica=False)
                except Exception as ex:
                    logger.warning(f"Key transfer during join failed: {ex}")

            # Notify successor immediately
            await self.rpc_call(
                self.successor.address,
                "chord.notify",
                {"node_id": self.node_id, "address": self.address},
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to join ring via {bootstrap_address}: {e}")
            return False

    async def stabilize(self) -> None:
        """Periodically verify successor and notify it."""
        try:
            # Check successor's predecessor
            pred_data = await self.rpc_call(self.successor.address, "chord.getPredecessor", {})
            if pred_data is not None:
                x = NodeRef(**pred_data)
                # If x is closer to us than current successor: in (n, successor)
                if in_interval_open(x.node_id, self.node_id, self.successor.node_id, self.m):
                    self.successor = x
                    self.finger_table[0] = x
        except Exception:
            # Successor failed! Switch to second entry in successor list (self-healing)
            logger.info(f"Successor {self.successor.node_id} failed. Promoting backup successor.")
            if len(self.successor_list) > 1 and self.successor_list[1].node_id != self.node_id:
                self.successor = self.successor_list[1]
                self.finger_table[0] = self.successor
                # Promote replicas to primary
                self.store.promote_replicas_to_primary()
            else:
                self.successor = self.self_ref
                self.finger_table[0] = self.self_ref

        # Notify successor
        try:
            if self.successor.node_id != self.node_id:
                await self.rpc_call(
                    self.successor.address,
                    "chord.notify",
                    {"node_id": self.node_id, "address": self.address},
                )
                # Update successor list from successor
                succ_list_data = await self.rpc_call(self.successor.address, "chord.getSuccessorList", {})
                if isinstance(succ_list_data, list) and succ_list_data:
                    first = self.successor
                    second = NodeRef(**succ_list_data[0]) if succ_list_data[0]["node_id"] != self.node_id else self.self_ref
                    self.successor_list = [first, second]
        except Exception as e:
            logger.debug(f"Stabilize notify failed: {e}")

    async def notify(self, candidate: NodeRef) -> bool:
        """Candidate thinks it might be our predecessor."""
        if (
            self.predecessor is None
            or in_interval_open(candidate.node_id, self.predecessor.node_id, self.node_id, self.m)
        ):
            self.predecessor = candidate
            return True
        return False

    async def fix_fingers(self) -> None:
        """Periodically refresh one entry in the finger table."""
        self.next_finger = (self.next_finger + 1) % self.m
        target_id = (self.node_id + (1 << self.next_finger)) % (1 << self.m)
        try:
            res = await self.find_successor(target_id)
            self.finger_table[self.next_finger] = NodeRef(node_id=res.node_id, address=res.address)
        except Exception:
            pass

    async def check_predecessor(self) -> None:
        """Check if predecessor is still alive."""
        if self.predecessor is not None and self.predecessor.node_id != self.node_id:
            try:
                await self.rpc_call(self.predecessor.address, "ping", {})
            except Exception:
                logger.info(f"Predecessor {self.predecessor.node_id} is dead; setting to None.")
                self.predecessor = None

    async def handle_put(self, key: str, value: Any, replicate: bool = True) -> bool:
        """Store key-value pair locally and replicate to successor if required."""
        self.store.put(key, value, is_replica=not replicate)
        if replicate and self.successor.node_id != self.node_id:
            try:
                await self.rpc_call(
                    self.successor.address,
                    "chord.put",
                    {"key": key, "value": value, "replicate": False},
                )
            except Exception as e:
                logger.warning(f"Replication to {self.successor.node_id} failed: {e}")
        return True

    async def handle_get(self, key: str) -> Optional[Any]:
        """Look up key in local primary or replica store."""
        return self.store.get(key)

    async def handle_delete(self, key: str) -> bool:
        """Delete key from local store and replica."""
        res = self.store.delete(key)
        if self.successor.node_id != self.node_id:
            try:
                await self.rpc_call(self.successor.address, "chord.delete", {"key": key})
            except Exception:
                pass
        return res

    async def handle_transfer_keys(self, new_node_id: int, succ_id: int) -> Dict[str, Any]:
        """Transfer responsibility for keys in (predecessor, new_node_id]."""
        pred_id = self.predecessor.node_id if self.predecessor else self.node_id
        keys = self.store.get_keys_in_range(pred_id, new_node_id)
        self.store.delete_keys_in_range(pred_id, new_node_id)
        return keys
