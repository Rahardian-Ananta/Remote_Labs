"""Tests for MPI runner and example scripts."""

import os
import pytest
from common.models import JobStatus
from executor.mpi_runner import execute_mpi_job, is_mpi_available


@pytest.mark.asyncio
async def test_mpi_invalid_num_ranks():
    code = "print('dummy')"
    # num_ranks = 0
    res = await execute_mpi_job(code, num_ranks=0, max_ranks=4)
    assert res.status == JobStatus.FAILED
    assert "Invalid num_ranks" in res.stderr

    # num_ranks = 5 > max_ranks 4
    res2 = await execute_mpi_job(code, num_ranks=5, max_ranks=4)
    assert res2.status == JobStatus.FAILED
    assert "Invalid num_ranks" in res2.stderr


@pytest.mark.skipif(
    not is_mpi_available(),
    reason="MPI runtime (OpenMPI/MS-MPI) not available on host; full implementation provided for Docker/Linux runtime",
)
@pytest.mark.asyncio
async def test_mpi_parallel_sum():
    example_path = os.path.join(os.path.dirname(__file__), "..", "examples", "mpi", "parallel_sum.py")
    with open(example_path, "r", encoding="utf-8") as f:
        code = f.read()

    res = await execute_mpi_job(code, num_ranks=2, max_ranks=4, timeout_sec=20)
    assert res.status == JobStatus.SUCCESS
    assert "Verification: SUCCESS" in res.stdout


@pytest.mark.skipif(
    not is_mpi_available(),
    reason="MPI runtime (OpenMPI/MS-MPI) not available on host; full implementation provided for Docker/Linux runtime",
)
@pytest.mark.asyncio
async def test_mpi_pagerank():
    example_path = os.path.join(os.path.dirname(__file__), "..", "examples", "mpi", "pagerank.py")
    with open(example_path, "r", encoding="utf-8") as f:
        code = f.read()

    res = await execute_mpi_job(code, num_ranks=2, max_ranks=4, timeout_sec=30)
    assert res.status == JobStatus.SUCCESS
    assert "Verification: SUCCESS" in res.stdout


@pytest.mark.skipif(
    not is_mpi_available(),
    reason="MPI runtime (OpenMPI/MS-MPI) not available on host; full implementation provided for Docker/Linux runtime",
)
@pytest.mark.asyncio
async def test_mpi_ring():
    example_path = os.path.join(os.path.dirname(__file__), "..", "examples", "mpi", "ring_isend_irecv.py")
    with open(example_path, "r", encoding="utf-8") as f:
        code = f.read()

    res = await execute_mpi_job(code, num_ranks=2, max_ranks=4, timeout_sec=20)
    assert res.status == JobStatus.SUCCESS
    assert "Verification: SUCCESS" in res.stdout

