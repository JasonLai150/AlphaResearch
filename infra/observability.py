"""Sentry observability: single init + recursive secret scrubber + alpha.* tag helper.

init_observability() is a silent no-op when SENTRY_DSN is unset, so local/dev/CI
runs require no Sentry and make no network calls. scrub() is import-safe without
sentry-sdk and is used both by before_send hooks and by manual breadcrumb payloads.
"""

from __future__ import annotations

import os
from typing import Any

_SECRET_SUBSTRINGS = frozenset({
    "api_key", "apikey", "token", "password", "passwd",
    "authorization", "cookie", "secret", "credential",
    "auth_", "_auth", "private_key", "access_key", "client_secret",
})
_MAX_STR_LEN = 2_000
_MAX_COLLECTION = 50


def init_observability(service_name: str) -> None:
    """Initialize Sentry. Silent no-op when SENTRY_DSN is unset."""
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        return

    import sentry_sdk
    from sentry_sdk.integrations.asyncio import AsyncioIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    integrations: list = [
        AsyncioIntegration(),
        LoggingIntegration(event_level=None, level=None),
    ]
    try:
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        integrations += [StarletteIntegration(), FastApiIntegration()]
    except ImportError:
        pass

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT", "development"),
        release=os.getenv("SENTRY_RELEASE") or None,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "1.0")),
        profiles_sample_rate=float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", "0.0")),
        server_name=service_name,
        integrations=integrations,
        before_send=_scrub_event,
        before_send_transaction=_scrub_event,
        send_default_pii=False,
    )
    sentry_sdk.set_tag("alpha.service", service_name)


def scrub(obj: Any, _depth: int = 0) -> Any:
    """Redact secret-like keys and bound payload size. Safe without sentry-sdk."""
    if _depth > 8:
        return "[max_depth]"
    if isinstance(obj, dict):
        items = list(obj.items())
        truncated = len(items) > _MAX_COLLECTION
        result: dict = {}
        for k, v in items[:_MAX_COLLECTION]:
            result[str(k)] = "[REDACTED]" if _is_secret(str(k)) else scrub(v, _depth + 1)
        if truncated:
            result["__truncated__"] = True
        return result
    if isinstance(obj, (list, tuple)):
        truncated = len(obj) > _MAX_COLLECTION
        out = [scrub(v, _depth + 1) for v in list(obj)[:_MAX_COLLECTION]]
        if truncated:
            out.append("[truncated]")
        return out
    if isinstance(obj, str) and len(obj) > _MAX_STR_LEN:
        excess = len(obj) - _MAX_STR_LEN
        return f"{obj[:_MAX_STR_LEN]}...[+{excess} chars]"
    return obj


def tag_alpha(
    span=None,
    *,
    session_id=None, job_id=None, parent_job_id=None, depth=None,
    job_kind=None, backend=None, event_type=None, model=None, tool=None,
) -> None:
    """Set the stable alpha.*/ai.* tags on a span/transaction (or current scope when
    span is None). None values are skipped. No-op tag setters when Sentry is disabled."""
    import sentry_sdk

    setter = span.set_tag if span is not None else sentry_sdk.set_tag
    pairs = {
        "alpha.session_id": session_id,
        "alpha.job_id": job_id,
        "alpha.parent_job_id": parent_job_id,
        "alpha.depth": depth,
        "alpha.job_kind": job_kind,
        "alpha.dispatch_backend": backend,
        "alpha.event_type": event_type,
        "ai.model": model,
        "ai.tool.name": tool,
    }
    for k, v in pairs.items():
        if v is not None:
            setter(k, str(v))


def _is_secret(key: str) -> bool:
    lower = key.lower()
    return any(s in lower for s in _SECRET_SUBSTRINGS)


def _scrub_event(event: dict, hint: dict | None = None) -> dict:
    for section in ("extra", "tags", "contexts"):
        if section in event:
            event[section] = scrub(event[section])
    for crumb in (event.get("breadcrumbs") or {}).get("values") or []:
        if "data" in crumb:
            crumb["data"] = scrub(crumb["data"])
    for span in event.get("spans") or []:
        if "data" in span:
            span["data"] = scrub(span["data"])
    return event
