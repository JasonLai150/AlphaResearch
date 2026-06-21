"""API surface for autonomous loops: bootstrap carries loop state, the agent
reports a round, and the runner-internal endpoints enforce session ownership."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from infra import store
from infra.schemas import RoundRecord
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


async def test_bootstrap_includes_loop_state(client, fake_redis):
    await store.create_session("s_a", "u", "improve return", 100, mode="autonomous")
    await store.create_loop("s_a", max_rounds=5, goal_metric=0.9, current_job_id="j_r")
    await store.append_round("s_a", RoundRecord(round_index=1, job_id="j_r", best_metric=0.4))
    await store.get_redis().json().set(store._session_key("s_a"), "$.root_job_id", "j_r")
    tok = await store.mint_agent_token("s_a")

    r = await client.get("/internal/bootstrap", headers=_bearer(tok))
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "autonomous"
    assert body["loop"]["round"] == 2  # one round done -> next is round 2
    assert body["loop"]["prior_rounds"][0]["best_metric"] == 0.4


async def test_oneshot_bootstrap_has_no_loop(client, fake_redis):
    await store.create_session("s_o", "u", "g", 100)  # oneshot
    await store.get_redis().json().set(store._session_key("s_o"), "$.root_job_id", "j_r")
    tok = await store.mint_agent_token("s_o")
    body = (await client.get("/internal/bootstrap", headers=_bearer(tok))).json()
    assert "loop" not in body


async def test_agent_reports_a_round(client, fake_redis):
    await store.create_session("s_a", "u", "g", 100, mode="autonomous")
    await store.create_loop("s_a", max_rounds=5)
    tok = await store.mint_agent_token("s_a")

    r = await client.post("/internal/loop/round",
                          json={"session_id": "s_a", "job_id": "j_1", "round_index": 1,
                                "plan_id": "plan_x", "best_metric": 0.42, "summary": "ok"},
                          headers=_bearer(tok))
    assert r.status_code == 202, r.text
    loop = await store.get_loop("s_a")
    assert loop.rounds[-1].best_metric == 0.42
    assert loop.rounds[-1].plan_id == "plan_x"


async def test_duplicate_round_report_is_idempotent(client, fake_redis):
    # A retrying agent must not be able to inflate len(rounds) and trip max_rounds.
    await store.create_session("s_a", "u", "g", 100, mode="autonomous")
    await store.create_loop("s_a", max_rounds=5)
    tok = await store.mint_agent_token("s_a")
    body = {"session_id": "s_a", "job_id": "j_1", "round_index": 1, "best_metric": 0.4}
    r1 = await client.post("/internal/loop/round", json=body, headers=_bearer(tok))
    r2 = await client.post("/internal/loop/round", json=body, headers=_bearer(tok))
    assert r1.status_code == 202 and r2.status_code == 202
    assert r2.json().get("duplicate") is True
    assert len((await store.get_loop("s_a")).rounds) == 1  # counted once


async def test_round_report_rejects_foreign_session(client, fake_redis):
    await store.create_session("s_a", "u", "g", 100, mode="autonomous")
    await store.create_loop("s_a", max_rounds=5)
    tok_b = await store.mint_agent_token("s_b")  # token for a different session
    r = await client.post("/internal/loop/round",
                          json={"session_id": "s_a", "job_id": "j_1", "round_index": 1},
                          headers=_bearer(tok_b))
    assert r.status_code == 403
