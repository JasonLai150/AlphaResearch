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
    claims = jwt.decode(
        token,
        signing_key,
        algorithms=["RS256"],
        issuer=settings.clerk_issuer or None,
        options={"verify_aud": False, "verify_iss": bool(settings.clerk_issuer)},
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
