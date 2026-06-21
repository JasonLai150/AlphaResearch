"""Public API authorization: the per-session ownership guard (IDOR fix).

Pure unit tests of orchestrator.auth.require_session_access — no Redis (fake or
real): the session lookup is stubbed and Clerk JWT verification is stubbed
(token string == user id), so this isolates the authn+authz logic. The full
flow against real Redis is covered by the live end-to-end verification.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import orchestrator.auth as auth
from infra.config import settings
from infra.schemas import Session

pytestmark = pytest.mark.asyncio


@pytest.fixture
def clerk_on(monkeypatch):
    """Pretend Clerk is configured; treat the bearer token AS the user id."""
    monkeypatch.setattr(settings, "clerk_jwks_url", "https://example/jwks")
    monkeypatch.setattr(settings, "clerk_issuer", "https://example")
    monkeypatch.setattr(auth, "_verify", lambda token: token)


@pytest.fixture
def session_owned_by(monkeypatch):
    def _set(user_id: str | None):
        async def _get(sid: str):
            return None if user_id is None else Session(id=sid, user_id=user_id, goal="g")

        monkeypatch.setattr("infra.store.get_session", _get)

    return _set


async def test_owner_allowed(clerk_on, session_owned_by):
    session_owned_by("userA")
    assert await auth.require_session_access("s_a", "Bearer userA") == "userA"


async def test_cross_user_blocked(clerk_on, session_owned_by):
    session_owned_by("userA")
    with pytest.raises(HTTPException) as e:
        await auth.require_session_access("s_a", "Bearer userB")
    assert e.value.status_code == 404  # 404 (not 403) so it doesn't leak existence


async def test_missing_session_blocked(clerk_on, session_owned_by):
    session_owned_by(None)
    with pytest.raises(HTTPException) as e:
        await auth.require_session_access("s_x", "Bearer userA")
    assert e.value.status_code == 404


async def test_missing_token_rejected(clerk_on):
    with pytest.raises(HTTPException) as e:
        await auth.require_session_access("s_a", None)
    assert e.value.status_code == 401


async def test_dev_mode_open(monkeypatch):
    # No Clerk configured -> open dev mode, returns None, no ownership check.
    monkeypatch.setattr(settings, "clerk_jwks_url", None)
    assert await auth.require_session_access("s_a", None) is None
