"""FastAPI API: create sessions, stream the per-session event bus over SSE.

SSE is a pure `XREAD BLOCK` tailer of `session:{sid}:events` — it does not host the
agent. For local/hackathon use, depth-0 `run_agent` runs as an in-process background
task (plan §7 single-service shortcut); the decoupled path is `orchestrator/worker.py`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agent.run_agent import run_agent
from infra import store
from infra.config import settings
from infra.schemas import EventEnvelope, EventType, Job, JobKind

app = FastAPI(title="AlphaResearch API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve local artifacts in dev (GCS serves them in prod).
Path(settings.artifacts_dir).mkdir(parents=True, exist_ok=True)
app.mount("/artifacts", StaticFiles(directory=settings.artifacts_dir), name="artifacts")


class CreateSession(BaseModel):
    goal: str
    user_id: str = "user"
    budget: int | None = None


@app.post("/sessions")
async def create_session(body: CreateSession) -> dict:
    sid = store.new_id("s")
    root = store.new_id("j")
    await store.create_session(sid, body.user_id, body.goal, body.budget or settings.default_budget)
    await store.create_job(
        Job(id=root, session_id=sid, depth=0, kind=JobKind.agent, params={"goal": body.goal})
    )
    asyncio.create_task(_run_root(root))
    return {"session_id": sid, "root_job_id": root}


async def _run_root(root_id: str) -> None:
    try:
        await run_agent(root_id)
    except Exception as exc:  # surface as a failed-status event so the UI isn't left hanging
        job = await store.get_job(root_id)
        if job:
            await store.set_job_status(root_id, "failed")
            await store.emit_event(
                EventEnvelope(
                    session_id=job.session_id,
                    job_id=root_id,
                    depth=0,
                    type=EventType.status,
                    payload={"status": "failed", "error": str(exc)},
                )
            )


@app.get("/sessions/{sid}")
async def get_session(sid: str) -> dict:
    return await store.read_state(sid)


@app.get("/sessions/{sid}/stream")
async def stream(sid: str, request: Request, last_event_id: str | None = Header(default=None)):
    # On first connect (no Last-Event-ID) replay from the start so the UI never
    # misses events the in-process run already emitted; reconnects pass a real id
    # and resume exactly after it.
    start = last_event_id or "0"

    async def gen():
        async for entry_id, env in store.tail_events(sid, start):
            if await request.is_disconnected():
                break
            yield {"id": entry_id, "event": env.type.value, "data": env.model_dump_json()}

    return EventSourceResponse(gen())


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
