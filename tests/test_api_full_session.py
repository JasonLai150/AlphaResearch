"""API surface (Task 7): session creation, full-session resume, internal router
mount + auth, and SEV-5 OpenAPI hiding. Uses httpx ASGITransport so requests and
the fakeredis instance share one event loop (and lifespan/runner never starts)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def client(fake_redis):
    from orchestrator import api as api_mod
    api_mod.app.openapi_schema = None  # rebuild schema per test (cache is module-level)
    async with AsyncClient(transport=ASGITransport(app=api_mod.app), base_url="http://t") as c:
        yield c


async def test_post_session_requires_user_id(client):
    r = await client.post("/sessions", json={"goal": "explore"})
    assert r.status_code == 422


async def test_post_session_returns_ids_and_persists(client):
    r = await client.post("/sessions", json={"user_id": "u_1", "goal": "explore"})
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"].startswith("s_")
    assert body["root_job_id"].startswith("j_")


async def test_get_full_session_returns_tree_and_transcript(client):
    r = await client.post("/sessions", json={"user_id": "u_1", "goal": "explore"})
    root_id = r.json()["root_job_id"]
    sid = r.json()["session_id"]
    full = (await client.get(f"/sessions/{sid}/full")).json()
    assert full["session"]["id"] == sid
    assert full["session"]["root_job_id"] == root_id  # persisted for the runner
    assert any(j["depth"] == 0 and j["backend"] == "cloud_run_job" for j in full["jobs"])
    assert full["transcript"] == []


async def test_internal_router_mounted_requires_auth(client):
    r = await client.post("/internal/events",
                          json={"session_id": "s_a", "job_id": "j_1", "depth": 0,
                                "type": "log", "payload": {}})
    assert r.status_code == 401  # mounted, but auth-required


async def test_internal_routes_hidden_from_openapi(client):
    schema = (await client.get("/openapi.json")).json()
    assert not any(p.startswith("/internal") for p in schema.get("paths", {}))
    assert "/sessions" in schema.get("paths", {})  # public routes still present
