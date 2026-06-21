"""The store seam: ALL Redis + GCS access lives here (plan §2.5 deliverable #1).

Loop/agent code calls only these functions, never redis-py or google-cloud-storage
directly. Entities are RedisJSON docs; the per-session event bus and the session
queue are Redis Streams; the budget is a plain atomic integer.
"""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import redis.asyncio as redis

from infra.config import settings
from infra.schemas import (
    ArtifactRef,
    EventEnvelope,
    EventType,
    Job,
    JobStatus,
    RunResult,
    Session,
)

_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        # Generous, resilient connection settings: Redis Cloud connect latency is
        # variable (~0.2-3s), which trips redis.asyncio's tight default connect
        # timeout intermittently. Keepalive + retry_on_timeout keep the long-lived
        # event-stream tailers and the worker consumer stable.
        _redis = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=15,
            socket_timeout=30,
            socket_keepalive=True,
            health_check_interval=30,
            retry_on_timeout=True,
        )
    return _redis


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# ---- keys ---------------------------------------------------------------

def _session_key(sid: str) -> str:
    return f"session:{sid}"


def _budget_key(sid: str) -> str:
    return f"session:{sid}:budget"


def _job_key(jid: str) -> str:
    return f"job:{jid}"


def _run_key(jid: str) -> str:
    return f"run:{jid}"


def _events_key(sid: str) -> str:
    return f"session:{sid}:events"


def _children_key(jid: str) -> str:
    return f"job:{jid}:children"


def _session_jobs_key(sid: str) -> str:
    return f"session:{sid}:jobs"


SESSIONS_QUEUE = "sessions:queue"


# ---- sessions -----------------------------------------------------------

async def create_session(session_id: str, user_id: str, goal: str, budget: int) -> Session:
    r = get_redis()
    s = Session(id=session_id, user_id=user_id, goal=goal)
    await r.json().set(_session_key(session_id), "$", s.model_dump())
    await r.set(_budget_key(session_id), int(budget))
    return s


async def get_session(session_id: str) -> Session | None:
    doc = await get_redis().json().get(_session_key(session_id))
    return Session.model_validate(doc) if doc else None


async def read_state(session_id: str) -> dict:
    """Materialized snapshot for the UI / debugging: session + jobs + runs."""
    r = get_redis()
    session = await get_session(session_id)
    job_ids = await r.smembers(_session_jobs_key(session_id))
    jobs = [j for j in [await get_job(jid) for jid in job_ids] if j]
    runs = [run for run in [await get_run(jid) for jid in job_ids] if run]
    budget = await r.get(_budget_key(session_id))
    return {
        "session": session.model_dump() if session else None,
        "budget": int(budget) if budget is not None else None,
        "jobs": [j.model_dump() for j in jobs],
        "runs": [run.model_dump() for run in runs],
    }


# ---- jobs ---------------------------------------------------------------

async def create_job(job: Job) -> Job:
    r = get_redis()
    await r.json().set(_job_key(job.id), "$", job.model_dump())
    await r.sadd(_session_jobs_key(job.session_id), job.id)
    if job.parent_job_id:
        await r.sadd(_children_key(job.parent_job_id), job.id)
    return job


async def get_job(job_id: str) -> Job | None:
    doc = await get_redis().json().get(_job_key(job_id))
    return Job.model_validate(doc) if doc else None


async def update_job(job_id: str, **fields) -> None:
    r = get_redis()
    for k, v in fields.items():
        await r.json().set(_job_key(job_id), f"$.{k}", v)


async def set_job_status(job_id: str, status: JobStatus | str) -> None:
    status = status.value if isinstance(status, JobStatus) else status
    await update_job(job_id, status=status)


async def get_children(job_id: str) -> list[str]:
    return sorted(await get_redis().smembers(_children_key(job_id)))


async def get_session_jobs(session_id: str) -> list[str]:
    return sorted(await get_redis().smembers(_session_jobs_key(session_id)))


async def get_root_job(session_id: str) -> str | None:
    for jid in await get_session_jobs(session_id):
        job = await get_job(jid)
        if job and job.depth == 0:
            return jid
    return None


# ---- runs (final results, flow UP) -------------------------------------

async def write_run(run: RunResult) -> None:
    await get_redis().json().set(_run_key(run.job_id), "$", run.model_dump())


async def get_run(job_id: str) -> RunResult | None:
    doc = await get_redis().json().get(_run_key(job_id))
    return RunResult.model_validate(doc) if doc else None


async def get_children_runs(job_id: str) -> list[RunResult]:
    runs = []
    for cid in await get_children(job_id):
        run = await get_run(cid)
        if run:
            runs.append(run)
    return runs


# ---- budget (atomic) ----------------------------------------------------

async def decr_budget(session_id: str, cost: int) -> int:
    """Atomic DECRBY; returns remaining balance (may be negative)."""
    return await get_redis().decrby(_budget_key(session_id), cost)


async def incr_budget(session_id: str, cost: int) -> int:
    return await get_redis().incrby(_budget_key(session_id), cost)


def _fanout_key(job_id: str) -> str:
    return f"job:{job_id}:fanout"


async def claim_fanout(parent_job_id: str, limit: int) -> bool:
    """Atomically reserve one fanout slot under a parent. Returns False (and refunds)
    if over the limit — closes the check-then-act race on the children set."""
    n = await get_redis().incr(_fanout_key(parent_job_id))
    if n > limit:
        await get_redis().decr(_fanout_key(parent_job_id))
        return False
    return True


async def release_fanout(parent_job_id: str) -> None:
    await get_redis().decr(_fanout_key(parent_job_id))


# ---- events (per-session bus) ------------------------------------------

async def emit_event(event: EventEnvelope) -> str:
    """XADD to the session event Stream. Returns the (monotonic) entry id."""
    return await get_redis().xadd(
        _events_key(event.session_id), {"data": event.model_dump_json()}
    )


_STREAM_ID_RE = re.compile(r"^\d+(-(\d+|\*))?$")  # <ms> or <ms>-<seq> / <ms>-*


def _normalize_last_id(last_id: str) -> str:
    if last_id in ("$", "0", "+", "-") or _STREAM_ID_RE.match(last_id):
        return last_id
    return "$"  # malformed/hostile Last-Event-ID -> behave as "only new events"


async def tail_events(
    session_id: str, last_id: str = "$"
) -> AsyncIterator[tuple[str, EventEnvelope]]:
    """Blocking tailer for the SSE endpoint. `last_id='$'` = only new events;
    `'0'` replays full history then tails; a real entry id resumes after it.
    """
    r = get_redis()
    stream = _events_key(session_id)
    last_id = _normalize_last_id(last_id)
    while True:
        resp = await r.xread({stream: last_id}, block=15000, count=100)
        if not resp:
            continue
        for _stream, entries in resp:
            for entry_id, fields in entries:
                last_id = entry_id
                yield entry_id, EventEnvelope.model_validate_json(fields["data"])


# ---- queue (depth-0 sessions for the worker) ---------------------------

async def enqueue_session(session_id: str) -> str:
    return await get_redis().xadd(SESSIONS_QUEUE, {"session_id": session_id})


# ---- artifacts (GCS in prod, local fallback in dev) --------------------

async def put_artifact(
    session_id: str,
    job_id: str,
    kind: str,
    data: bytes,
    name: str,
    caption: str | None = None,
    content_type: str = "application/octet-stream",
) -> ArtifactRef:
    aid = new_id("a")
    if settings.gcs_bucket:
        url = await asyncio.to_thread(
            _upload_gcs, session_id, job_id, name, data, content_type
        )
    else:
        url = _upload_local(session_id, job_id, name, data)
    ref = ArtifactRef(id=aid, job_id=job_id, kind=kind, url=url, caption=caption, bytes=len(data))
    await get_redis().json().set(f"artifact:{aid}", "$", ref.model_dump())
    await emit_event(
        EventEnvelope(
            session_id=session_id,
            job_id=job_id,
            type=EventType.artifact,
            payload={"artifact_id": aid, "kind": kind, "url": url, "caption": caption},
        )
    )
    return ref


def _upload_local(session_id: str, job_id: str, name: str, data: bytes) -> str:
    base = Path(settings.artifacts_dir) / session_id / job_id
    base.mkdir(parents=True, exist_ok=True)
    (base / name).write_bytes(data)
    # Served by the API as static files under /artifacts (see orchestrator/api.py).
    return f"/artifacts/{session_id}/{job_id}/{name}"


def _upload_gcs(session_id: str, job_id: str, name: str, data: bytes, content_type: str) -> str:
    import json

    from google.cloud import storage  # lazy: only needed when GCS configured

    if settings.storage_emulator_host:
        os.environ.setdefault("STORAGE_EMULATOR_HOST", settings.storage_emulator_host)
        client = storage.Client()
    elif settings.google_credentials_b64:
        # Modal: SA key injected as single-line base64 (no file on disk).
        import base64

        client = storage.Client.from_service_account_info(
            json.loads(base64.b64decode(settings.google_credentials_b64))
        )
    elif settings.google_credentials_json:
        client = storage.Client.from_service_account_info(
            json.loads(settings.google_credentials_json)
        )
    elif settings.google_credentials_file:
        # Local: explicit SA key file (.env isn't exported to os.environ for ADC).
        client = storage.Client.from_service_account_json(settings.google_credentials_file)
    else:
        client = storage.Client()  # ADC fallback
    path = f"{session_id}/{job_id}/{name}"
    bucket = client.bucket(settings.gcs_bucket)
    bucket.blob(path).upload_from_string(data, content_type=content_type)
    # Browser-loadable public URL (bucket is public-read for the demo). The local-disk
    # fallback returns a relative /artifacts/... path; the web client handles both.
    return f"https://storage.googleapis.com/{settings.gcs_bucket}/{path}"


__all__ = [
    "get_redis", "new_id", "create_session", "get_session", "read_state",
    "create_job", "get_job", "update_job", "set_job_status", "get_children",
    "get_session_jobs", "get_root_job",
    "write_run", "get_run", "get_children_runs", "decr_budget", "incr_budget",
    "emit_event", "tail_events", "enqueue_session", "put_artifact",
    "claim_fanout", "release_fanout", "SESSIONS_QUEUE",
]
