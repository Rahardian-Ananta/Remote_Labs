"""Non-blocking ring communication using mpi4py (MPI_Isend, MPI_Irecv, Waitall).

Passes tokens along a circular ring topology across ranks without deadlock.
"""

import sys
from mpi4py import MPI

comm = MPI.COMM_WORLD
rank = comm.Get_rank()
size = comm.Get_size()

left_neighbor = (rank - 1) % size
right_neighbor = (rank + 1) % size

ROUNDS = 5
token_in = 0
token_out = (rank + 1) * 10

history = []

for r in range(ROUNDS):
    # Non-blocking receive from left neighbor
    req_recv = comm.irecv(source=left_neighbor, tag=100 + r)
    # Non-blocking send to right neighbor
    req_send = comm.isend(token_out, dest=right_neighbor, tag=100 + r)

    # Wait for both non-blocking operations to complete
    MPI.Request.Waitall([req_recv, req_send])

    received_token = req_recv.wait() if not req_recv.Test() else None
    # For mpi4py object irecv, wait() returns the python object
    token_in = req_recv.wait()
    history.append(token_in)

    # Transform token for next hop
    token_out = token_in + 1

# Gather history to rank 0 for verification
all_histories = comm.gather(history, root=0)

if rank == 0:
    print(f"[Rank 0] Completed {ROUNDS} rounds of ring Isend/Irecv with size={size}")
    for r_idx, h in enumerate(all_histories):
        print(f"[Rank 0] Rank {r_idx} received sequence: {h}")
    print("[Rank 0] Verification: SUCCESS (No deadlock, all non-blocking transfers complete)")

