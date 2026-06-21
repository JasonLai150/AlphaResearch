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


# ---- bootstrap ---------------------------------------------------------

async def test_bootstrap_requires_auth(client):
    r = await client.get("/internal/bootstrap")
    assert r.status_code == 401


async def test_bootstrap_returns_goal_and_mode(client, fake_redis):
    await store.create_session("s_a", "u_1", "improve DoorKey sample efficiency", 100)
    # root_job_id is stamped on the session doc by POST /sessions; mirror that here.
    await fake_redis.json().set(store._session_key("s_a"), "$.root_job_id", "j_root")
    tok = await store.mint_agent_token("s_a")
    r = await client.get("/internal/bootstrap", headers=_bearer(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "s_a"
    assert body["goal"] == "improve DoorKey sample efficiency"
    assert body["mode"] == "oneshot"
    assert body["root_job_id"] == "j_root"
    assert body["depth"] == 0


async def test_bootstrap_rejects_cross_session_isolation(client, fake_redis):
    """A token for s_b returns s_b's (empty) context, never s_a's goal."""
    await store.create_session("s_a", "u_1", "secret goal A", 100)
    tok_b = await store.mint_agent_token("s_b")
    r = await client.get("/internal/bootstrap", headers=_bearer(tok_b))
    # s_b has no session doc → 404 (not a leak of s_a)
    assert r.status_code == 404


async def test_bootstrap_unbound_token_400(client, fake_redis, monkeypatch):
    from infra.config import settings
    monkeypatch.setattr(settings, "internal_token_fallback", True)
    r = await client.get("/internal/bootstrap", headers=_bearer(settings.internal_token))
    assert r.status_code == 400  # shared dev token isn't session-bound


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


# ---- result (PR2) ------------------------------------------------------

import base64  # noqa: E402


async def test_result_records_run_and_artifact(client, fake_redis, monkeypatch):
    from infra import store as store_mod
    monkeypatch.setattr(store_mod.settings, "gcs_bucket", "")  # use local artifact path
    await _seed_parent()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               kind=JobKind.agent, status=JobStatus.running))
    tok = await store.mint_agent_token("s_a")
    png = base64.b64encode(b"PNGDATA").decode()
    r = await client.post("/internal/result",
                          json={"job_id": "j_c", "session_id": "s_a", "status": "done",
                                "summary": "got 0.8", "metrics": {"score": 0.8},
                                "artifacts": [{"name": "p.png", "kind": "plot", "b64": png}]},
                          headers=_bearer(tok))
    assert r.status_code == 202 and r.json()["recorded"] is True
    assert (await store.get_job("j_c")).status == JobStatus.done
    run = await store.get_run("j_c")
    assert run.status == "done" and run.metrics["score"] == 0.8
    arts = await store.list_artifacts_for("j_c")
    assert len(arts) == 1 and arts[0].kind == "plot"


async def test_result_failed_status_marks_job_failed(client, fake_redis):
    await _seed_parent()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               kind=JobKind.agent, status=JobStatus.running))
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/result",
                          json={"job_id": "j_c", "session_id": "s_a", "status": "failed",
                                "summary": "diverged"},
                          headers=_bearer(tok))
    assert r.status_code == 202
    assert (await store.get_job("j_c")).status == JobStatus.failed


async def _seed_child_with_plan(target_metric="score"):
    await _seed_parent()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               kind=JobKind.agent, status=JobStatus.running,
                               params={"plan": {"target_metric": target_metric},
                                       "idea_id": "idea_1"}))


async def test_result_done_passes_contract_with_target_metric(client, fake_redis):
    """A clean success that carries the plan's target_metric stays 'done'."""
    await _seed_child_with_plan(target_metric="score")
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/result",
                          json={"job_id": "j_c", "session_id": "s_a", "status": "done",
                                "summary": "ok", "metrics": {"score": 0.8}},
                          headers=_bearer(tok))
    assert r.status_code == 202 and r.json()["contract_violations"] == []
    run = await store.get_run("j_c")
    assert run.status == "done" and run.contract_violations == []
    assert (await store.get_job("j_c")).status == JobStatus.done


async def test_result_done_missing_target_metric_downgraded_to_partial(client, fake_redis):
    """Idea 1: a 'done' claim with no target_metric is recorded but downgraded to
    'partial' with the violation attached — never silently ranked as a real finding."""
    await _seed_child_with_plan(target_metric="mean_return_at_500k_steps")
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/result",
                          json={"job_id": "j_c", "session_id": "s_a", "status": "done",
                                "summary": "claims success", "metrics": {"some_other_key": 1.0}},
                          headers=_bearer(tok))
    assert r.status_code == 202
    viol = r.json()["contract_violations"]
    assert any("mean_return_at_500k_steps" in v for v in viol)
    run = await store.get_run("j_c")
    assert run.status == "partial" and run.contract_violations == viol
    # never dropped — the result is still recorded, job still terminal.
    assert (await store.get_job("j_c")).status == JobStatus.done


async def test_result_validated_without_baseline_downgraded(client, fake_redis):
    """validated:true demands a baseline comparison; a claim with the target metric but
    no baseline is downgraded and de-validated."""
    await _seed_child_with_plan(target_metric="score")
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/result",
                          json={"job_id": "j_c", "session_id": "s_a", "status": "done",
                                "summary": "no baseline run", "validated": True,
                                "metrics": {"score": 0.9}},
                          headers=_bearer(tok))
    assert r.status_code == 202
    run = await store.get_run("j_c")
    assert run.status == "partial" and run.validated is False
    assert any("baseline" in v for v in run.contract_violations)


async def test_result_single_seed_trainer_result_passes(client, fake_redis):
    """The prebaked trainer is single-seed by design and writes validated:true with a
    baseline + delta. The structural contract must accept it unchanged (no downgrade) —
    seed-rigor is a separate concern, not a structural violation."""
    await _seed_child_with_plan(target_metric="mean_return")
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/result",
                          json={"job_id": "j_c", "session_id": "s_a", "status": "done",
                                "summary": "trainer ran baseline+intervention", "validated": True,
                                "metrics": {"mean_return": 0.7, "mean_return_baseline": 0.5,
                                            "delta_vs_baseline": 0.2, "n_seeds": 1}},
                          headers=_bearer(tok))
    assert r.status_code == 202 and r.json()["contract_violations"] == []
    run = await store.get_run("j_c")
    assert run.status == "done" and run.validated is True


async def test_result_failed_not_contract_checked(client, fake_redis):
    """An honest negative finding (status=failed) is allowed to be thin — no contract
    violations forced on it."""
    await _seed_child_with_plan(target_metric="score")
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/result",
                          json={"job_id": "j_c", "session_id": "s_a", "status": "failed",
                                "summary": "no improvement", "metrics": {}},
                          headers=_bearer(tok))
    assert r.status_code == 202 and r.json()["contract_violations"] == []
    assert (await store.get_job("j_c")).status == JobStatus.failed


async def test_result_is_idempotent(client, fake_redis):
    await _seed_parent()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               kind=JobKind.agent, status=JobStatus.running))
    tok = await store.mint_agent_token("s_a")
    body = {"job_id": "j_c", "session_id": "s_a", "status": "done", "summary": "first"}
    r1 = await client.post("/internal/result", json=body, headers=_bearer(tok))
    r2 = await client.post("/internal/result", json={**body, "summary": "second"},
                           headers=_bearer(tok))
    assert r1.status_code == 202 and r2.status_code == 202
    assert r2.json().get("duplicate") is True
    assert (await store.get_run("j_c")).summary == "first"  # first write wins


async def test_result_rejects_cross_session(client, fake_redis):
    await _seed_parent(sid="s_a", jid="j_root")
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               kind=JobKind.agent, status=JobStatus.running))
    tok_b = await store.mint_agent_token("s_b")
    r = await client.post("/internal/result",
                          json={"job_id": "j_c", "session_id": "s_b", "status": "done"},
                          headers=_bearer(tok_b))
    assert r.status_code in (403, 404)  # token owns s_b; job lives in s_a


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
    """A foreign token must not be able to distinguish 'exists elsewhere' from
    'not found' — both collapse to 404 (no cross-session existence oracle)."""
    await _seed_parent(sid="s_a", jid="j_root")
    tok_b = await store.mint_agent_token("s_b")
    r = await client.get("/internal/children/j_root", headers=_bearer(tok_b))
    assert r.status_code == 404
    # and a genuinely missing parent for the owning token is also 404
    tok_a = await store.mint_agent_token("s_a")
    r2 = await client.get("/internal/children/j_missing", headers=_bearer(tok_a))
    assert r2.status_code == 404


async def test_dispatch_rejects_invalid_kind(client, fake_redis):
    """Garbage 'kind' is rejected at validation (422) — never reaches claim_fanout."""
    await _seed_parent()
    tok = await store.mint_agent_token("s_a")
    r = await client.post("/internal/dispatch",
                          json={"job_id": "j_c", "parent_job_id": "j_root", "session_id": "s_a",
                                "depth": 1, "kind": "totally-bogus"},
                          headers=_bearer(tok))
    assert r.status_code == 422


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
