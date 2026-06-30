"""End-to-end (backend half): the local-sim scripted run streams `console` events
onto the SAME per-session events stream the SSE endpoint tails — for the lead
agent (stderr) and for sub-agents (stdout training lines) — and never leaks raw
console into the chat transcript. Exercises the real local_sim + real store
against fakeredis; no cloud, no sleeps.
"""

from __future__ import annotations

import pytest

from infra import store
from infra.schemas import EventEnvelope, EventType, Job, JobKind, JobStatus, Message
from runner import local_sim

pytestmark = pytest.mark.asyncio


async def test_local_sim_streams_console_to_the_sse_event_stream(fake_redis, monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(local_sim.asyncio, "sleep", no_sleep)

    sid, root = "s_con", "j_root"
    await store.create_session(sid, "u1", "improve PPO sample efficiency", 100)
    await store.create_job(
        Job(id=root, session_id=sid, depth=0, kind=JobKind.agent,
            params={"goal": "g"}, status=JobStatus.queued)
    )
    await fake_redis.json().set(store._session_key(sid), "$.root_job_id", root)

    await local_sim.run_local_sim_session(sid)

    rows = await fake_redis.xrange(f"session:{sid}:events")
    evs = [EventEnvelope.model_validate_json(v["data"]) for _, v in rows]
    console = [e for e in evs if e.type is EventType.console]

    assert console, "expected console events on the SSE event stream"
    # Lead agent streamed its operational stderr...
    assert any(e.job_id == root and e.payload["stream"] == "stderr" for e in console)
    # ...and at least one sub-agent streamed stdout (training) lines, tagged to it.
    assert any(e.job_id != root and e.payload["stream"] == "stdout" for e in console)
    # Every console event carries a line payload (what the UI renders).
    assert all(isinstance(e.payload.get("line"), str) and e.payload["line"] for e in console)

    # Console must ride the events stream only — never the chat transcript.
    tr = await fake_redis.xrange(f"session:{sid}:transcript")
    msgs = [Message.model_validate_json(v["data"]) for _, v in tr]
    assert all("step=" not in m.content for m in msgs)
