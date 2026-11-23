"""Tests for executor/sandbox.py."""

import pytest
from common.models import JobStatus
from executor.sandbox import execute_in_sandbox


@pytest.mark.asyncio
async def test_sandbox_normal_execution():
    code = "print('RemoteLab Sandbox Active')"
    result = await execute_in_sandbox(code, timeout_sec=5)
    assert result.status == JobStatus.SUCCESS
    assert result.exit_code == 0
    assert "RemoteLab Sandbox Active" in result.stdout
    assert result.duration_ms > 0
    assert not result.truncated


@pytest.mark.asyncio
async def test_sandbox_timeout():
    code = "import time\ntime.sleep(10)"
    result = await execute_in_sandbox(code, timeout_sec=2)
    assert result.status == JobStatus.TIMEOUT
    assert result.exit_code == -1
    assert "timed out" in result.stderr.lower()


@pytest.mark.asyncio
async def test_sandbox_exception_failed():
    code = "raise ValueError('Explicit test error')"
    result = await execute_in_sandbox(code, timeout_sec=5)
    assert result.status == JobStatus.FAILED
    assert result.exit_code != 0
    assert "ValueError: Explicit test error" in result.stderr


@pytest.mark.asyncio
async def test_sandbox_output_truncation():
    # Generate ~200 KB of output with limit 50 KB
    code = "for _ in range(5000):\n    print('A' * 40)"
    result = await execute_in_sandbox(code, timeout_sec=5, max_output_bytes=50000)
    assert result.truncated is True
    assert len(result.stdout.encode("utf-8")) <= 50000

