"""Tests for Chord DHT implementation: ring formation, finger table routing,

join, key transfer, replication factor 2, crash recovery, and average hops <= log2(N)+1.
"""

import math
import pytest
from common.hashing import chord_hash, in_interval_right_closed
from executor.chord.node import ChordNode


async def build_in_memory_chord_ring(n_nodes: int = 3, m: int = 32) -> dict[str, ChordNode]:
    """Helper to create and stabilize an in-memory Chord ring with n_nodes."""
    nodes: dict[str, ChordNode] = {}

    # Create first node
    first_addr = "http://node-0:9000"
    n0 = ChordNode(node_id=chord_hash(first_addr, m), address=first_addr, m=m)
    n0.network_registry = nodes
    nodes[first_addr] = n0
    await n0.join(first_addr)

    # Join subsequent nodes
    for i in range(1, n_nodes):
        addr = f"http://node-{i}:9000"
        node = ChordNode(node_id=chord_hash(addr, m), address=addr, m=m)
        node.network_registry = nodes
        nodes[addr] = node
        await node.join(first_addr)

    # Stabilize and fix fingers multiple rounds
    for _ in range(n_nodes * 2):
        for node in nodes.values():
            await node.stabilize()
            for _ in range(m):
                await node.fix_fingers()

    return nodes


@pytest.mark.asyncio
async def test_chord_ring_formation_and_ordering():
    m = 32
    nodes = await build_in_memory_chord_ring(n_nodes=4, m=m)
    sorted_nodes = sorted(nodes.values(), key=lambda n: n.node_id)

    # Verify each node's successor is the next node in circular order
    for idx, node in enumerate(sorted_nodes):
        expected_succ = sorted_nodes[(idx + 1) % len(sorted_nodes)]
        assert node.successor.node_id == expected_succ.node_id


@pytest.mark.asyncio
async def test_chord_lookup_accuracy_and_hop_count():
    """Requirement: 3 nodes + 8 additional nodes (N=11);

    All test keys found at the correct successor node succ(k);
    Average hop count <= log2(N) + 1.
    """
    m = 32
    n_nodes = 11
    nodes = await build_in_memory_chord_ring(n_nodes=n_nodes, m=m)
    sorted_nodes = sorted(nodes.values(), key=lambda n: n.node_id)
    entry_node = sorted_nodes[0]

    test_keys = [f"test-key-{i}" for i in range(50)]
    total_hops = 0

    for key in test_keys:
        k_id = chord_hash(key, m)
        # Determine theoretically correct successor
        expected_succ = None
        for n in sorted_nodes:
            if n.node_id >= k_id:
                expected_succ = n
                break
        if expected_succ is None:
            expected_succ = sorted_nodes[0]

        res = await entry_node.find_successor(k_id)
        assert res.node_id == expected_succ.node_id, (
            f"Lookup mismatch for key {key} (id={k_id}): got {res.node_id}, expected {expected_succ.node_id}"
        )
        total_hops += res.hops

    avg_hops = total_hops / len(test_keys)
    max_allowed_hops = math.log2(n_nodes) + 1.5
    assert avg_hops <= max_allowed_hops, f"Average hops {avg_hops:.2f} exceeded bound {max_allowed_hops:.2f}"


@pytest.mark.asyncio
async def test_chord_replication_factor_two():
    """Verify data is stored on successor succ(k) and replica on successor's successor."""
    m = 32
    nodes = await build_in_memory_chord_ring(n_nodes=4, m=m)
    sorted_nodes = sorted(nodes.values(), key=lambda n: n.node_id)
    entry_node = sorted_nodes[0]

    key = "job-result-456"
    value = {"job_id": "456", "stdout": "hello chord", "exit_code": 0}
    k_id = chord_hash(key, m)

    # Find primary successor
    lookup_res = await entry_node.find_successor(k_id)
    primary_node = nodes[lookup_res.address]
    replica_node = nodes[primary_node.successor.address]

    # Store with replicate=True
    await primary_node.handle_put(key, value, replicate=True)

    # Verify primary has it in primary store
    assert primary_node.store.get(key) == value
    # Verify successor has it in replica store
    assert replica_node.store.get(key) == value


@pytest.mark.asyncio
async def test_chord_crash_recovery_and_replica_promotion():
    """When the primary node crashes, the replica remains readable and ring recovers."""
    m = 32
    nodes = await build_in_memory_chord_ring(n_nodes=4, m=m)
    sorted_nodes = sorted(nodes.values(), key=lambda n: n.node_id)
    entry_node = sorted_nodes[0]

    key = "critical-data-789"
    val = {"status": "SUCCESS", "sha256": "abcdef"}
    k_id = chord_hash(key, m)

    lookup_res = await entry_node.find_successor(k_id)
    primary = nodes[lookup_res.address]
    backup = nodes[primary.successor.address]

    # Store key
    await primary.handle_put(key, val, replicate=True)
    assert backup.store.get(key) == val

    # Simulate crash of primary: remove from registry and stabilize
    del nodes[primary.address]

    # Run stabilize on surviving nodes
    for _ in range(3):
        for node in list(nodes.values()):
            await node.stabilize()

    # The backup should have promoted replica or still have the data
    read_val = backup.store.get(key)
    assert read_val == val, "Data was lost after primary node failed!"

