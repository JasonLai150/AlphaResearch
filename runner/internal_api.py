"""The runner's internal HTTP API. Agents (main-agent on Cloud Run, sub-agents on
Modal) POST telemetry + dispatch records here and query child status.

Security (SEV-4 + SEV-5):
  * Every route authenticates a **per-session ephemeral token** (store.resolve_agent_token).
    A token only ever acts on the session it was minted for — a leaked token cannot
    drive /internal/* against another session. A shared bootstrap token is accepted
    ONLY when settings.internal_token_fallback is true (dev), and even then it carries
    no session binding (so it cannot be used to escalate cross-session in prod config).
  * /internal/dispatch validates parent ownership + depth (parent.depth+1, <= max_depth)
    and a fanout cap, so a compromised main-agent cannot spawn arbitrary work.
  * All routes set include_in_schema=False → they never appear in /openapi.json or /docs.
"""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass

import sentry_sdk
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel, Field

from infra import store
from infra.config import settings
from infra.observability import tag_alpha
from infra.schemas import (
    EventEnvelope,
    EventType,
    Job,
    JobKind,
    JobStatus,
    Message,
    RunResult,
)

router = APIRouter(prefix="/internal", tags=["internal"])


@dataclass
class Caller:
    """Who's calling. ``session_id`` is None only for the dev shared-token fallback
    (unbound — handlers then skip the per-session ownership check)."""

    session_id: str | None


async def require_caller(authorization: str | None = Header(default=None)) -> Caller:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer")
    token = authorization.removeprefix("Bearer ").strip()
    sid = await store.resolve_agent_token(token)
    if sid:
        sentry_sdk.set_tag("alpha.session_id", sid)
        return Caller(session_id=sid)
    # Dev fallback only. Constant-time compare so the shared token can't be timing-probed.
    if settings.internal_token_fallback and secrets.compare_digest(
        token, settings.internal_token
    ):
        return Caller(session_id=None)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bad token")


def _enforce_session(caller: Caller, session_id: str) -> None:
    if caller.session_id is not None and caller.session_id != session_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "token does not own this session")


# ---- agent bootstrap ---------------------------------------------------
#
# The main agent has no shared filesystem with the runner and the user goal is never
# baked into its container — it fetches its context here on boot (token -> session).
# `mode` lets a future conversational flow refine the goal over turns before dispatch;
# for now it's always "oneshot". Designed to grow into returning the conversation.

@router.get("/bootstrap", include_in_schema=False)
async def get_bootstrap(caller: Caller = Depends(require_caller)) -> dict:
    sid = caller.session_id
    if sid is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "bootstrap requires a session-bound token")
    doc = await store.get_redis().json().get(store._session_key(sid))
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown session")
    return {
        "session_id": sid,
        "root_job_id": doc.get("root_job_id"),
        "goal": doc.get("goal", ""),
        "mode": doc.get("mode", "oneshot"),
        "depth": 0,
    }


# ---- request bodies ----------------------------------------------------

class EventIn(BaseModel):
    session_id: str
    job_id: str
    parent_job_id: str | None = None
    depth: int = 0
    type: EventType
    payload: dict = Field(default_factory=dict)


class TranscriptIn(BaseModel):
    session_id: str
    job_id: str
    role: str
    content: str = ""
    tool_name: str | None = None
    tool_input: dict | None = None


class DispatchIn(BaseModel):
    job_id: str
    parent_job_id: str
    session_id: str
    depth: int
    kind: JobKind = JobKind.agent  # enum-typed: garbage -> 422 at parse, before any side effect
    plan: dict | None = None
    idea_id: str | None = None
    strategy: str | None = None
    created_at: str | None = None


class ArtifactIn(BaseModel):
    name: str
    kind: str = "other"  # plot | checkpoint | log | other
    b64: str             # base64-encoded bytes
    caption: str | None = None


class ResultIn(BaseModel):
    job_id: str
    session_id: str
    status: str = "done"  # done | failed | partial
    summary: str = ""
    metrics: dict = Field(default_factory=dict)
    artifacts: list[ArtifactIn] = Field(default_factory=list)
    patch: str | None = None       # future-git seam
    base_ref: str | None = None


# ---- telemetry ---------------------------------------------------------

@router.post("/events", status_code=204, include_in_schema=False)
async def post_event(ev: EventIn, caller: Caller = Depends(require_caller)) -> Response:
    _enforce_session(caller, ev.session_id)
    await store.emit_event(EventEnvelope(
        session_id=ev.session_id, job_id=ev.job_id, parent_job_id=ev.parent_job_id,
        depth=ev.depth, type=ev.type, payload=ev.payload,
    ))
    return Response(status_code=204)


@router.post("/transcript", status_code=204, include_in_schema=False)
async def post_transcript(m: TranscriptIn, caller: Caller = Depends(require_caller)) -> Response:
    _enforce_session(caller, m.session_id)
    await store.append_message(Message(**m.model_dump()))
    return Response(status_code=204)


# ---- dispatch (main-agent registers a sub-agent) -----------------------

@router.post("/dispatch", status_code=202, include_in_schema=False)
async def post_dispatch(d: DispatchIn, caller: Caller = Depends(require_caller)) -> dict:
    _enforce_session(caller, d.session_id)
    with sentry_sdk.start_span(op="alpha.internal.dispatch", name="dispatch") as span:
        tag_alpha(span, session_id=d.session_id, parent_job_id=d.parent_job_id,
                  job_id=d.job_id, depth=d.depth, job_kind=d.kind.value)
        parent = await store.get_job(d.parent_job_id)
        if parent is None:
            span.set_tag("alpha.dispatch_result", "unknown_parent")
            raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown parent job")
        if parent.session_id != d.session_id:
            span.set_tag("alpha.dispatch_result", "foreign_parent")
            raise HTTPException(status.HTTP_403_FORBIDDEN, "parent belongs to another session")
        if d.depth != parent.depth + 1:
            span.set_tag("alpha.dispatch_result", "bad_depth")
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"depth must be parent.depth+1 ({parent.depth + 1})")
        if d.depth > settings.max_depth:
            span.set_tag("alpha.dispatch_result", "max_depth")
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"max_depth={settings.max_depth} exceeded")

        # Idempotent: a retried POST for an already-registered job is a no-op success.
        if await store.get_job(d.job_id) is not None:
            span.set_tag("alpha.dispatch_result", "duplicate")
            return {"queued": True, "duplicate": True}

        if not await store.claim_fanout(d.parent_job_id, settings.max_fanout):
            span.set_tag("alpha.dispatch_result", "max_fanout")
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                f"max_fanout={settings.max_fanout} reached")
        try:
            child = Job(
                id=d.job_id, session_id=d.session_id, parent_job_id=d.parent_job_id,
                depth=d.depth, kind=d.kind, status=JobStatus.queued, backend="modal",
                params={"plan": d.plan, "idea_id": d.idea_id, "strategy": d.strategy},
            )
            await store.create_job(child)  # also links parent + session-jobs index
            await store.enqueue_dispatch(d.job_id)
            await store.emit_event(EventEnvelope(
                session_id=d.session_id, job_id=d.job_id, parent_job_id=d.parent_job_id,
                depth=d.depth, type=EventType.spawn,
                payload={"strategy": d.strategy, "idea_id": d.idea_id},
            ))
        except Exception:
            await store.release_fanout(d.parent_job_id)  # don't permanently burn the slot
            raise
        span.set_tag("alpha.dispatch_result", "queued")
        return {"queued": True}


# ---- result (sub-agent pushes its RunResult + artifacts) ---------------

_ARTIFACT_SIZE_CAP = 10 * 1024 * 1024  # 10MB/artifact (Cloud Run ~32MB request cap)


@router.post("/result", status_code=202, include_in_schema=False)
async def post_result(r: ResultIn, caller: Caller = Depends(require_caller)) -> dict:
    """PR2: a sub-agent reports its result here instead of writing a shared volume.
    Records the RunResult, uploads its (base64) artifacts to GCS, and flips job status.
    Idempotent: the finalize hook may retry, so a second POST for an already-recorded
    job is a no-op success."""
    _enforce_session(caller, r.session_id)
    job = await store.get_job(r.job_id)
    if job is None or job.session_id != r.session_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown job")
    if await store.get_run(r.job_id) is not None:
        return {"recorded": True, "duplicate": True}

    for a in r.artifacts:
        try:
            data = base64.b64decode(a.b64, validate=True)
        except Exception:  # noqa: BLE001 — skip one bad artifact, never drop the result
            continue
        if not data or len(data) > _ARTIFACT_SIZE_CAP:
            continue
        await store.put_artifact(r.session_id, r.job_id, a.kind, data, a.name, a.caption)

    status_l = (r.status or "done").lower()
    if status_l not in ("done", "failed", "partial"):
        status_l = "done"
    await store.write_run(RunResult(job_id=r.job_id, status=status_l, summary=r.summary,
                                    metrics=r.metrics, patch=r.patch, base_ref=r.base_ref))
    await store.set_job_status(
        r.job_id, JobStatus.failed if status_l == "failed" else JobStatus.done)
    await store.emit_event(EventEnvelope(
        session_id=r.session_id, job_id=r.job_id, parent_job_id=job.parent_job_id,
        depth=job.depth, type=EventType.summary,
        payload={"summary": r.summary[:240], "metrics": r.metrics,
                 "reported_status": status_l}))
    return {"recorded": True}


# ---- child status / artifacts (main-agent polls these) -----------------

def _owned_or_404(caller: Caller, parent) -> None:
    """Collapse 'not found' and 'foreign session' into one 404 so a token can't be
    used as a cross-session existence oracle (enumerate job ids by 404-vs-403)."""
    if parent is None or (caller.session_id is not None and parent.session_id != caller.session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown parent job")


@router.get("/children/{parent_job_id}", include_in_schema=False)
async def get_children(parent_job_id: str, caller: Caller = Depends(require_caller)) -> list[dict]:
    _owned_or_404(caller, await store.get_job(parent_job_id))
    return await store.child_statuses(parent_job_id)


@router.get("/children/{parent_job_id}/artifacts", include_in_schema=False)
async def get_children_artifacts(
    parent_job_id: str, caller: Caller = Depends(require_caller)
) -> dict:
    _owned_or_404(caller, await store.get_job(parent_job_id))
    out: dict[str, list[dict]] = {}
    for cjid in await store.get_children(parent_job_id):
        out[cjid] = [a.model_dump(mode="json") for a in await store.list_artifacts_for(cjid)]
    return out
