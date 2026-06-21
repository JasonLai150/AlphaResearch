"""Real conversational chat turns (replaces the local-sim mock). A user follow-up
is handed to a fresh main-agent turn: the runner's chat_loop drains chat:inbox and
re-spawns the lead agent (reusing the root job so the reply lands in the main
transcript), and /internal/bootstrap hands that turn the new message + transcript.
"""

from __future__ import annotations

import pytest

from infra import store
from infra.schemas import Job, JobKind, JobStatus
from runner import loops

pytestmark = pytest.mark.asyncio


async def _seed_session(fake_redis, *, root_status=JobStatus.done):
    sid, root = "s_chat", "j_root"
    await store.create_session(sid, "u1", "improve PPO", 100)
    await store.create_job(Job(id=root, session_id=sid, depth=0, kind=JobKind.agent,
                               params={"goal": "improve PPO"}, status=root_status))
    await fake_redis.json().set(store._session_key(sid), "$.root_job_id", root)
    return sid, root


# ---- store: pending-chat handoff ---------------------------------------

async def test_pending_chat_set_get_pop(fake_redis):
    assert await store.get_pending_chat("s_a") is None
    await store.set_pending_chat("s_a", "what about a higher lr?")
    assert await store.get_pending_chat("s_a") == "what about a higher lr?"
    # pop returns it once, then it's gone (so a re-bootstrap doesn't re-answer).
    assert await store.pop_pending_chat("s_a") == "what about a higher lr?"
    assert await store.get_pending_chat("s_a") is None
    assert await store.pop_pending_chat("s_a") is None


# ---- runner chat_loop: re-spawn the lead agent for a follow-up turn -----

async def test_chat_loop_respawns_lead_agent_for_a_follow_up(fake_redis, monkeypatch):
    sid, root = await _seed_session(fake_redis, root_status=JobStatus.done)
    calls: list[tuple] = []

    async def fake_spawn(s, j, **kw):
        calls.append((s, j))
        return "exec_chat_1"

    monkeypatch.setattr(loops, "spawn_main_agent_job", fake_spawn)

    await store.enqueue_chat(sid, "try a higher learning rate?")
    await loops._consume_chats_once()

    # The new turn re-spawns the lead agent, reusing the root job (reply -> main chat).
    assert calls == [(sid, root)]
    # The message is staged for that turn's bootstrap.
    assert await store.get_pending_chat(sid) == "try a higher learning rate?"
    # Root flipped running with the new execution as its sandbox.
    job = await store.get_job(root)
    assert job.status is JobStatus.running and job.sandbox_id == "exec_chat_1"
    # The inbox entry was consumed.
    assert await store.read_stream(store.CHAT_INBOX, "0", 50, 0) == []


async def test_chat_loop_defers_while_a_turn_is_already_running(fake_redis, monkeypatch):
    sid, root = await _seed_session(fake_redis, root_status=JobStatus.running)
    calls: list[tuple] = []

    async def fake_spawn(s, j, **kw):
        calls.append((s, j))
        return "x"

    monkeypatch.setattr(loops, "spawn_main_agent_job", fake_spawn)

    await store.enqueue_chat(sid, "follow-up while busy")
    await loops._consume_chats_once()

    # Lead is mid-turn: don't spawn a second; leave the message queued for next pass.
    assert calls == []
    assert await store.get_pending_chat(sid) is None
    queued = await store.read_stream(store.CHAT_INBOX, "0", 50, 0)
    assert len(queued) == 1 and queued[0][1]["content"] == "follow-up while busy"
