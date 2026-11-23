"""Parallel Sum using mpi4py (MPI_Bcast, MPI_Scatter, MPI_Reduce).

Compares distributed sum across ranks with sequential sum.
"""

import sys
import numpy as np
from mpi4py import MPI

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()

N = 100_000

# Rank 0 prepares parameters and data
if rank == 0:
    data = np.arange(1, N + 1, dtype=np.int64)
    # Ensure divisible chunking
    chunks = np.array_split(data, size)
    n_elements = N
else:
    chunks = None
    n_elements = None

# 1. MPI_Bcast total elements count to all ranks
n_elements = comm.bcast(n_elements, root=0)

# 2. MPI_Scatter array chunks to all ranks
local_chunk = comm.scatter(chunks, root=0)

# Each rank computes local partial sum
local_sum = int(np.sum(local_chunk))

# 3. MPI_Reduce local sums to rank 0 using MPI.SUM
total_parallel_sum = comm.reduce(local_sum, op=MPI.SUM, root=0)

# Rank 0 verifies against sequential calculation
if rank == 0:
    sequential_sum = int(np.sum(data))
    assert total_parallel_sum == sequential_sum, f"Mismatch: {total_parallel_sum} != {sequential_sum}"
    print(f"[Rank 0] Parallel Sum: {total_parallel_sum}")
    print(f"[Rank 0] Sequential Sum: {sequential_sum}")
    print(f"[Rank 0] Verification: SUCCESS (Ranks = {size}, Elements = {n_elements})")

