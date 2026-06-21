"""Runner internal API: telemetry, dispatch, child queries — and the SEV-4
per-session token security model + SEV-5 dispatch validation."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from infra import store
from infra.schemas import Job, JobKind, JobStatus, RunResult
from runner.internal_api import router

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app(fake_redis):
    a = FastAPI()
    a.include_router(router)
    return a


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---- auth --------------------------------------------------------------

async def test_events_requires_auth(client):
    r = await client.post("/internal/events", json={"session_id": "s_a", "job_id": "j_1",
                                                     "depth": 0, "type": "log", "payload": {}})
    assert r.status_code == 401


async def test_events_rejects_bad_token(client):
    r = await client.post("/internal/events",
                          json={"session_id": "s_a", "job_id": "j_1", "depth": 0,
                                "type": "log", "payload": {}},
                          headers=_bearer("not-a-real-token"))
    assert r.status_code == 401


async def test_events_writes_with_valid_session_token(client, fake_redis):
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/events",
                          json={"session_id": "s_a", "job_id": "j_1", "depth": 0,
                                "type": "log", "payload": {"msg": "hi"}},
                          headers=_bearer(tok))
    assert r.status_code == 204
    entries = await fake_redis.xrange("session:s_a:events", "-", "+")
    assert len(entries) == 1


async def test_events_rejects_cross_session_token(client, fake_redis):
    """SEV-4: a token minted for s_a cannot write events for s_b."""
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/events",
                          json={"session_id": "s_b", "job_id": "j_1", "depth": 0,
                                "type": "log", "payload": {}},
                          headers=_bearer(tok))
    assert r.status_code == 403


async def test_transcript_writes_message(client, fake_redis):
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/transcript",
                          json={"session_id": "s_a", "job_id": "j_1", "role": "user",
                                "content": "hi"},
                          headers=_bearer(tok))
    assert r.status_code == 204
    entries = await fake_redis.xrange("session:s_a:transcript", "-", "+")
    assert len(entries) == 1


async def test_bad_event_type_422(client, fake_redis):
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/events",
                          json={"session_id": "s_a", "job_id": "j_1", "depth": 0,
                                "type": "not-an-enum", "payload": {}},
                          headers=_bearer(tok))
    assert r.status_code == 422


# ---- dispatch ----------------------------------------------------------

async def _seed_parent(sid="s_a", jid="j_root", depth=0):
    await store.create_session(sid, "u_1", "g", 100)
    await store.create_job(Job(id=jid, session_id=sid, depth=depth, kind=JobKind.agent,
                               status=JobStatus.running))


async def test_dispatch_creates_child_and_enqueues(client, fake_redis):
    await _seed_parent()
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/dispatch",
                          json={"job_id": "j_c", "parent_job_id": "j_root", "session_id": "s_a",
                                "depth": 1, "kind": "agent", "plan": {"id": "p"},
                                "idea_id": "idea_1", "strategy": "exploration: x"},
                          headers=_bearer(tok))
    assert r.status_code == 202 and r.json()["queued"] is True
    child = await store.get_job("j_c")
    assert child is not None and child.parent_job_id == "j_root" and child.depth == 1
    assert child.status == JobStatus.queued
    entries = await store.read_stream(store.DISPATCH_QUEUE, last_id="0", count=10, block_ms=0)
    assert any(f["job_id"] == "j_c" for _, f in entries)


async def test_dispatch_is_idempotent(client, fake_redis):
    await _seed_parent()
    tok = await store.mint_agent_token("s_a")
    body = {"job_id": "j_c", "parent_job_id": "j_root", "session_id": "s_a", "depth": 1,
            "kind": "agent", "plan": {}, "idea_id": "i", "strategy": "s"}
    r1 = await client.post("/internal/dispatch", json=body, headers=_bearer(tok))
    r2 = await client.post("/internal/dispatch", json=body, headers=_bearer(tok))
    assert r1.status_code == 202 and r2.status_code == 202
    assert r2.json().get("duplicate") is True
    entries = await store.read_stream(store.DISPATCH_QUEUE, last_id="0", count=10, block_ms=0)
    assert sum(1 for _, f in entries if f["job_id"] == "j_c") == 1  # enqueued once


async def test_dispatch_rejects_bad_depth(client, fake_redis):
    await _seed_parent()
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/dispatch",
                          json={"job_id": "j_c", "parent_job_id": "j_root", "session_id": "s_a",
                                "depth": 3, "kind": "agent"},
                          headers=_bearer(tok))
    assert r.status_code == 400


async def test_dispatch_rejects_foreign_parent(client, fake_redis):
    """SEV-4: token for s_b cannot dispatch under s_a's parent job."""
    await _seed_parent(sid="s_a", jid="j_root")
    tok_b = await store.mint_agent_token("s_b")
    r = await client.post("/internal/dispatch",
                          json={"job_id": "j_c", "parent_job_id": "j_root", "session_id": "s_b",
                                "depth": 1, "kind": "agent"},
                          headers=_bearer(tok_b))
    # token owns s_b but the parent lives in s_a → 403 on session-binding or parent check
    assert r.status_code == 403


async def test_dispatch_rejects_fanout(client, fake_redis, monkeypatch):
    from infra.config import settings
    monkeypatch.setattr(settings, "max_fanout", 1)
    await _seed_parent()
    tok = await store.mint_agent_token("s_a")
    base = {"parent_job_id": "j_root", "session_id": "s_a", "depth": 1, "kind": "agent"}
    r1 = await client.post("/internal/dispatch", json={**base, "job_id": "j_1"},
                           headers=_bearer(tok))
    r2 = await client.post("/internal/dispatch", json={**base, "job_id": "j_2"},
                           headers=_bearer(tok))
    assert r1.status_code == 202
    assert r2.status_code == 429


# ---- children ----------------------------------------------------------

async def test_children_returns_statuses(client, fake_redis):
    await _seed_parent()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               kind=JobKind.agent, status=JobStatus.done))
    await store.write_run(RunResult(job_id="j_c", summary="ok", metrics={"r": 0.5}))
    tok = await store.mint_agent_token("s_a")
    r = await client.get("/internal/children/j_root", headers=_bearer(tok))
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1 and rows[0]["job_id"] == "j_c"
    assert rows[0]["done"] is True and rows[0]["summary"] == "ok"


async def test_children_artifacts(client, fake_redis):
    await _seed_parent()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               kind=JobKind.agent, status=JobStatus.done))
    await store.put_artifact("s_a", "j_c", "plot", b"PNG", "loss.png", "loss")
    tok = await store.mint_agent_token("s_a")
    r = await client.get("/internal/children/j_root/artifacts", headers=_bearer(tok))
    assert r.status_code == 200
    body = r.json()
    assert "j_c" in body and len(body["j_c"]) == 1 and body["j_c"][0]["kind"] == "plot"


async def test_children_rejects_cross_session(client, fake_redis):
    await _seed_parent(sid="s_a", jid="j_root")
    tok_b = await store.mint_agent_token("s_b")
    r = await client.get("/internal/children/j_root", headers=_bearer(tok_b))
    assert r.status_code == 403


# ---- shared-token fallback (dev only) ----------------------------------

async def test_shared_token_fallback_toggle(client, fake_redis, monkeypatch):
    from infra.config import settings
    # disabled by default → shared token rejected
    r = await client.post("/internal/events",
                          json={"session_id": "s_a", "job_id": "j_1", "depth": 0,
                                "type": "log", "payload": {}},
                          headers=_bearer(settings.internal_token))
    assert r.status_code == 401
    # enabled → accepted (unbound, any session)
    monkeypatch.setattr(settings, "internal_token_fallback", True)
    r = await client.post("/internal/events",
                          json={"session_id": "s_a", "job_id": "j_1", "depth": 0,
                                "type": "log", "payload": {}},
                          headers=_bearer(settings.internal_token))
    assert r.status_code == 204
