"""Cloud Run main-agent spawn — SEV-9: never record sandbox_id=None."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from runner import cloud_run_client

pytestmark = pytest.mark.asyncio


def _fake_jobs(exec_name):
    op = MagicMock()
    op.metadata = MagicMock()
    op.metadata.name = exec_name
    jobs = MagicMock()
    jobs.run_job = AsyncMock(return_value=op)
    return jobs


async def test_spawn_raises_when_no_execution_name(fake_redis):
    """SEV-9: a lazy/None op.metadata.name must raise, not silently store None."""
    with patch("runner.cloud_run_client._jobs", lambda: _fake_jobs(None)):
        with pytest.raises(RuntimeError):
            await cloud_run_client.spawn_main_agent_job("s_a", "j_root")


async def test_spawn_returns_execution_name(fake_redis):
    name = "projects/p/locations/us-central1/jobs/alpha-main-agent/executions/abc123"
    with patch("runner.cloud_run_client._jobs", lambda: _fake_jobs(name)):
        got = await cloud_run_client.spawn_main_agent_job("s_a", "j_root")
    assert got == name
