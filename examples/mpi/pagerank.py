"""Parallel PageRank algorithm using mpi4py (Scatter, Bcast, Allreduce).

Distributes transition matrix across ranks, broadcasts score vectors,
and checks convergence against sequential power iteration.
"""

import sys
import numpy as np
from mpi4py import MPI

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()

NUM_NODES = 120
DAMPING = 0.85
MAX_ITER = 30
TOLERANCE = 1e-5

# Deterministic random graph generation
rng = np.random.default_rng(seed=42)

if rank == 0:
    # Generate adjacency matrix
    adj = rng.binomial(1, 0.08, size=(NUM_NODES, NUM_NODES)).astype(np.float64)
    # Avoid zero out-degree rows by adding uniform links
    out_degrees = adj.sum(axis=1)
    for i in range(NUM_NODES):
        if out_degrees[i] == 0:
            adj[i, :] = 1.0 / NUM_NODES
        else:
            adj[i, :] = adj[i, :] / out_degrees[i]
    transition_matrix = adj.T  # Column-stochastic transition matrix
    matrix_chunks = np.array_split(transition_matrix, size, axis=0)
else:
    transition_matrix = None
    matrix_chunks = None

# Distribute row blocks of transition_matrix to ranks
local_matrix = comm.scatter(matrix_chunks, root=0)

# Initial uniform rank scores
p = np.full(NUM_NODES, 1.0 / NUM_NODES, dtype=np.float64)
teleport = (1.0 - DAMPING) / NUM_NODES

# Power iteration
for iteration in range(MAX_ITER):
    # Broadcast current score vector p
    p = comm.bcast(p, root=0)

    # Local matrix-vector multiplication
    local_p_next = DAMPING * np.dot(local_matrix, p) + teleport * (local_matrix.shape[0] / NUM_NODES)

    # Gather or Allgatherv full updated vector
    p_gathered = comm.gather(local_p_next, root=0)

    if rank == 0:
        p_next = np.concatenate(p_gathered)
        # Normalize
        p_next = p_next / np.sum(p_next)
        diff = np.linalg.norm(p_next - p, ord=1)
        p = p_next
        if diff < TOLERANCE:
            break

p = comm.bcast(p, root=0)

if rank == 0:
    # Compute sequential reference PageRank
    p_seq = np.full(NUM_NODES, 1.0 / NUM_NODES, dtype=np.float64)
    for _ in range(MAX_ITER):
        p_seq_next = DAMPING * np.dot(transition_matrix, p_seq) + (1.0 - DAMPING) / NUM_NODES
        p_seq_next = p_seq_next / np.sum(p_seq_next)
        diff = np.linalg.norm(p_seq_next - p_seq, ord=1)
        p_seq = p_seq_next
        if diff < TOLERANCE:
            break

    max_err = float(np.max(np.abs(p - p_seq)))
    assert max_err < 1e-4, f"PageRank error exceeds tolerance: {max_err}"
    print(f"[Rank 0] PageRank completed in {iteration + 1} iterations.")
    print(f"[Rank 0] Top 5 nodes by score: {np.argsort(p)[-5:][::-1].tolist()}")
    print(f"[Rank 0] Max difference from sequential: {max_err:.8f}")
    print("[Rank 0] Verification: SUCCESS (Parallel PageRank converged correctly)")

