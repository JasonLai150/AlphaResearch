"""Sub-agent Modal lifecycle: spawn passes the dispatch record as a call arg (PR2 —
no shared volume), and poll maps a FunctionCall to our tri-state. Modal SDK is mocked."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infra import store
from runner import modal_client

pytestmark = pytest.mark.asyncio


async def test_spawn_sub_agent_passes_record_and_token(fake_redis):
    await store.create_session("s_a", "u_1", "g", 100)
    await store.mint_agent_token("s_a")  # so get_session_token returns a token

    spawn_aio = AsyncMock(return_value=MagicMock(object_id="fc_123"))
    fake_fn = MagicMock(spawn=MagicMock(aio=spawn_aio))
    fake_modal = MagicMock()
    fake_modal.Function.from_name.return_value = fake_fn

    record = {"job_id": "j_c", "idea_id": "i", "plan": {"id": "p"}}
    with patch("runner.modal_client._modal", return_value=fake_modal):
        sb = await modal_client.spawn_sub_agent("j_c", "s_a", record)

    assert sb == "fc_123"
    kwargs = spawn_aio.await_args.kwargs
    assert kwargs["job_id"] == "j_c" and kwargs["session_id"] == "s_a"
    assert kwargs["internal_token"]  # a per-session token was injected
    assert json.loads(kwargs["dispatch_record"])["idea_id"] == "i"  # record serialized in


async def test_poll_modal_call_tristate():
    fc_done = MagicMock(get=MagicMock(aio=AsyncMock(return_value=None)))
    fc_run = MagicMock(get=MagicMock(aio=AsyncMock(side_effect=TimeoutError())))
    fc_fail = MagicMock(get=MagicMock(aio=AsyncMock(side_effect=ValueError("boom"))))

    for fc, expected in [(fc_done, "done"), (fc_run, "running"), (fc_fail, "failed")]:
        fake_modal = MagicMock()
        fake_modal.FunctionCall.from_id.return_value = fc
        with patch("runner.modal_client._modal", return_value=fake_modal):
            assert await modal_client.poll_modal_call("sb") == expected


async def test_poll_modal_call_transient_stays_running():
    fc = MagicMock(get=MagicMock(aio=AsyncMock(side_effect=ConnectionError("blip"))))
    fake_modal = MagicMock()
    fake_modal.FunctionCall.from_id.return_value = fc
    with patch("runner.modal_client._modal", return_value=fake_modal):
        assert await modal_client.poll_modal_call("sb") == "running"
