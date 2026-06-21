"""Optional Clerk auth for the public API.

With ``ALPHA_CLERK_JWKS_URL`` set, the public endpoints require a verified Clerk
session JWT (RS256, validated against Clerk's JWKS) and derive the user id from
the token ``sub``. Without it the API runs open (dev) and trusts a caller-supplied
user id. PyJWT is imported lazily, so the dev path needs no extra dependency.
"""

from __future__ import annotations

from fastapi import Header, HTTPException

from infra.config import settings

_jwks_client = None


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def _verify(token: str) -> str:
    global _jwks_client
    import jwt  # lazy: only needed when Clerk is configured

    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(settings.clerk_jwks_url)
    signing_key = _jwks_client.get_signing_key_from_jwt(token).key
    # issuer is required whenever JWKS is configured (enforced in Settings), so
    # verify_iss is always on here; audience is verified when configured.
    claims = jwt.decode(
        token,
        signing_key,
        algorithms=["RS256"],
        issuer=settings.clerk_issuer,
        audience=settings.clerk_audience,
        options={
            "verify_iss": True,
            "verify_aud": bool(settings.clerk_audience),
        },
    )
    sub = claims.get("sub")
    if not sub:
        raise ValueError("token missing sub")
    return str(sub)


async def verified_user_id(
    authorization: str | None = Header(default=None),
) -> str | None:
    """The verified Clerk user id, or None in keyless dev mode."""
    if not settings.clerk_jwks_url:
        return None
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="missing bearer token")
    try:
        return _verify(token)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="invalid token") from e


async def require_session_access(
    sid: str, authorization: str | None = Header(default=None)
) -> str | None:
    """Authn + authz for a session-scoped endpoint. Returns the verified user id
    (None in dev). When Clerk is on, 404s if the session isn't the caller's — 404
    rather than 403 so it doesn't leak which session ids exist."""
    uid = await verified_user_id(authorization)
    if uid is not None:
        from infra import store  # lazy to avoid import cycle

        session = await store.get_session(sid)
        if session is None or session.user_id != uid:
            raise HTTPException(status_code=404, detail="not found")
    return uid
