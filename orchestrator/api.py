"""FastAPI API: create sessions, stream the per-session event bus over SSE, expose
the full session snapshot for chat resume, and host the runner's internal API.

Creating a session enqueues it on `sessions:queue`; the RUNNER (asyncio loops in
this same process) consumes that, launches the depth-0 main-agent Cloud Run Job,
and writes job/run/event records back to Redis which the SSE endpoint streams.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from infra import store
from infra.config import settings
from infra.observability import init_observability
from infra.schemas import Job, JobKind, JobStatus
from runner.internal_api import router as internal_router

init_observability("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # SEV-13: establish + verify Redis before serving, so the first agent push never
    # races a cold-connect window and gets silently dropped.
    try:
        await store.ping()
    except Exception as e:  # noqa: BLE001
        print(f"[startup] redis ping failed (continuing): {e!r}")
    tasks = []
    if settings.runner_enabled:
        from runner.main import start_runner_tasks
        tasks = start_runner_tasks()
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()


app = FastAPI(title="AlphaResearch API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The internal API (agents -> runner) is authed per-session and hidden from the
# OpenAPI schema (SEV-5). Mounting it here keeps it on the same ASGI app.
app.include_router(internal_router)

# Serve local artifacts in dev (GCS serves them in prod).
Path(settings.artifacts_dir).mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=settings.artifacts_dir), name="artifacts")


def _public_openapi() -> dict:
    """SEV-5 defense-in-depth: never expose /internal/* in the published schema even
    if a route forgets include_in_schema=False."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(title=app.title, version="0.1.0", routes=app.routes)
    schema["paths"] = {
        p: v for p, v in schema.get("paths", {}).items() if not p.startswith("/internal")
    }
    app.openapi_schema = schema
    return schema


app.openapi = _public_openapi


class CreateSession(BaseModel):
    user_id: str          # required — multi-user sessions are keyed by it
    goal: str
    budget: int | None = None
    mode: Literal["oneshot", "autonomous"] = "oneshot"
    # autonomous only: hard cap on rounds (bounded so a typo can't spawn 10k jobs)
    max_rounds: int | None = Field(default=None, ge=1, le=50)
    goal_metric: float | None = None  # autonomous only: stop early once a round hits this


_DEFAULT_MAX_ROUNDS = 5


@app.post("/sessions")
async def create_session(body: CreateSession) -> dict:
    sid = store.new_id("s")
    root = store.new_id("j")
    await store.create_session(
        sid, body.user_id, body.goal, body.budget or settings.default_budget, mode=body.mode)
    await store.create_job(
        Job(id=root, session_id=sid, depth=0, kind=JobKind.agent,
            params={"goal": body.goal}, status=JobStatus.queued, backend="cloud_run_job")
    )
    # Record the root on the session doc so the runner finds it without scanning.
    # For an autonomous loop this is the CURRENT round's job; the runner re-points it
    # each round (see runner.loops._advance_loop).
    await store.get_redis().json().set(store._session_key(sid), "$.root_job_id", root)
    if body.mode == "autonomous":
        await store.create_loop(
            sid, max_rounds=body.max_rounds or _DEFAULT_MAX_ROUNDS,
            goal_metric=body.goal_metric, current_job_id=root)
    # Handoff: the runner consumes sessions:queue and launches the depth-0 main-agent.
    await store.enqueue_session(sid)
    return {"session_id": sid, "root_job_id": root}


@app.post("/sessions/{sid}/stop")
async def stop_session(sid: str) -> dict:
    """Request that an autonomous loop halt. Takes effect at the next round boundary
    (the runner reads stop_requested before deciding to spawn another round)."""
    loop = await store.get_loop(sid)
    if loop is None:
        return {"stopped": False, "reason": "session has no autonomous loop"}
    await store.request_loop_stop(sid)
    return {"stopped": True}


@app.get("/sessions/{sid}")
async def get_session(sid: str) -> dict:
    return await store.read_state(sid)


@app.get("/sessions/{sid}/full")
async def full_session(sid: str) -> dict:
    """Everything the chat UI needs to resume: session, job tree, runs, transcript,
    artifacts."""
    return await store.read_full_session(sid)


@app.get("/sessions/{sid}/stream")
async def stream(sid: str, request: Request, last_event_id: str | None = Header(default=None)):
    # On first connect (no Last-Event-ID) replay from the start so the UI never
    # misses events; reconnects pass a real id and resume exactly after it.
    start = last_event_id or "0"

    async def gen():
        async for entry_id, env in store.tail_events(sid, start):
            if await request.is_disconnected():
                break
            yield {"id": entry_id, "event": env.type.value, "data": env.model_dump_json()}

    return EventSourceResponse(gen())


# NOTE: the path is "/health", NOT "/healthz". Google Front End reserves the exact
# path "/healthz" on *.run.app and returns its own 404 before the request reaches the
# container, so a "/healthz" route is silently unreachable from outside Cloud Run
# (verified: every other path reaches the app; only "/healthz" is intercepted).
@app.get("/health")
async def health() -> dict:
    return {"ok": True}
