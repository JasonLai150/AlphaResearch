"""The store seam: ALL Redis + GCS access lives here (plan §2.5 deliverable #1).

Loop/agent code calls only these functions, never redis-py or google-cloud-storage
directly. Entities are RedisJSON docs; the per-session event bus and the session
queue are Redis Streams; the budget is a plain atomic integer.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import secrets
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
    Loop,
    LoopStatus,
    Message,
    RoundRecord,
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


def _status_set_key(status: JobStatus | str) -> str:
    v = status.value if isinstance(status, JobStatus) else str(status)
    return f"jobs:by_status:{v}"


SESSIONS_QUEUE = "sessions:queue"


async def ping() -> bool:
    """Eagerly establish + verify the Redis connection. Called on FastAPI startup
    (SEV-13) so the first agent push never races a cold connect window."""
    return bool(await get_redis().ping())


# ---- sessions -----------------------------------------------------------

async def create_session(
    session_id: str, user_id: str, goal: str, budget: int, mode: str = "oneshot"
) -> Session:
    r = get_redis()
    s = Session(id=session_id, user_id=user_id, goal=goal, mode=mode)
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


# ---- autonomous loops ---------------------------------------------------

def _loop_key(sid: str) -> str:
    return f"loop:{sid}"


def _loop_now() -> str:
    from infra.schemas import _now
    return _now()


async def create_loop(
    session_id: str, max_rounds: int, goal_metric: float | None = None,
    plateau_k: int = 3, current_job_id: str | None = None,
) -> Loop:
    loop = Loop(session_id=session_id, max_rounds=max_rounds, goal_metric=goal_metric,
                plateau_k=plateau_k, current_job_id=current_job_id)
    await get_redis().json().set(_loop_key(session_id), "$", loop.model_dump())
    return loop


async def get_loop(session_id: str) -> Loop | None:
    doc = await get_redis().json().get(_loop_key(session_id))
    return Loop.model_validate(doc) if doc else None


async def append_round(session_id: str, record: RoundRecord) -> None:
    r = get_redis()
    key = _loop_key(session_id)
    if not await r.exists(key):
        return
    async with r.pipeline(transaction=True) as p:
        p.json().arrappend(key, "$.rounds", record.model_dump())
        p.json().set(key, "$.updated_at", _loop_now())
        await p.execute()


async def set_loop_status(session_id: str, status: LoopStatus | str, reason: str = "") -> None:
    r = get_redis()
    key = _loop_key(session_id)
    if not await r.exists(key):
        return
    v = status.value if isinstance(status, LoopStatus) else str(status)
    async with r.pipeline(transaction=True) as p:
        p.json().set(key, "$.status", v)
        p.json().set(key, "$.stop_reason", reason)
        p.json().set(key, "$.updated_at", _loop_now())
        await p.execute()


async def request_loop_stop(session_id: str) -> None:
    r = get_redis()
    key = _loop_key(session_id)
    if not await r.exists(key):
        return
    await r.json().set(key, "$.stop_requested", True)


async def set_loop_current_job(session_id: str, job_id: str) -> None:
    r = get_redis()
    key = _loop_key(session_id)
    if not await r.exists(key):
        return
    await r.json().set(key, "$.current_job_id", job_id)


# ---- jobs ---------------------------------------------------------------

async def create_job(job: Job) -> Job:
    r = get_redis()
    await r.json().set(_job_key(job.id), "$", job.model_dump())
    await r.sadd(_session_jobs_key(job.session_id), job.id)
    await r.sadd(_status_set_key(job.status), job.id)  # status index (runner reconcile)
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
    """Field-level status write + status-index maintenance (SEV-3).

    We set only ``$.status`` (never whole-doc ``$``) so a concurrent write to
    another field — e.g. a hook-driven reconcile stamping ``sandbox_id`` — is not
    clobbered. The index move (SREM old / SADD new) runs in the same MULTI/EXEC.
    The read-of-old is benign even when stale: the runner is single-leader
    (SEV-2 lease) and ``reconcile`` re-fetches each job (SEV-12), so a transient
    stale index membership self-heals on the next pass.
    """
    new_v = status.value if isinstance(status, JobStatus) else str(status)
    r = get_redis()
    # Guard existence: on real Redis a JSON.SET of a sub-path against a missing key
    # errors at EXEC while the queued SADD/SREM still run, drifting the index. Skip
    # cleanly if the job doc is gone (re-fetch in reconcile already handles this).
    if not await r.exists(_job_key(job_id)):
        return
    # Index membership is a PURE FUNCTION of the final committed status: inside one
    # MULTI/EXEC we SET $.status, SADD the new set, and SREM the job from every OTHER
    # set — so the index can never drift, even under retries.
    async with r.pipeline(transaction=True) as p:
        p.json().set(_job_key(job_id), "$.status", new_v)
        for st in JobStatus:
            if st.value == new_v:
                p.sadd(_status_set_key(st), job_id)
            else:
                p.srem(_status_set_key(st), job_id)
        await p.execute()


async def mark_job_running(job_id: str, sandbox_id: str, backend: str) -> None:
    """Atomically stamp sandbox_id + backend + status=running + status-index move in
    ONE MULTI/EXEC (SEV: a crash between a separate update_job and set_job_status left
    the job 'queued' with a live sandbox — a lost job). No-op if the doc is gone."""
    r = get_redis()
    if not await r.exists(_job_key(job_id)):
        return
    running = JobStatus.running.value
    async with r.pipeline(transaction=True) as p:
        p.json().set(_job_key(job_id), "$.sandbox_id", sandbox_id)
        p.json().set(_job_key(job_id), "$.backend", backend)
        p.json().set(_job_key(job_id), "$.status", running)
        for st in JobStatus:
            if st.value == running:
                p.sadd(_status_set_key(st), job_id)
            else:
                p.srem(_status_set_key(st), job_id)
        await p.execute()


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
    # NOTE: the stream is intentionally NOT trimmed here. The frontend rebuilds
    # ALL view state by replaying this stream from "0" (see web/hooks/use-session.ts),
    # so a MAXLEN trim would silently drop chat/token history on reconnect. Console
    # streaming raises per-session volume; bounding it properly means a SEPARATE,
    # independently-capped console stream (+ its own SSE channel) — tracked as a
    # follow-up rather than capping the replay-critical events stream.
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
    aid = deterministic_artifact_id(session_id, job_id, name)  # SEV-10: idempotent re-puts
    if settings.gcs_bucket:
        url = await asyncio.to_thread(
            _upload_gcs, session_id, job_id, name, data, content_type
        )
    else:
        url = _upload_local(session_id, job_id, name, data)
    ref = ArtifactRef(id=aid, job_id=job_id, kind=kind, url=url, caption=caption, bytes=len(data))
    await get_redis().json().set(f"artifact:{aid}", "$", ref.model_dump())
    await link_artifact_to_job(job_id, aid)  # keep job:{jid}:artifacts index consistent
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


def _gcs_client():
    """Single GCS credential-resolution path, shared by store.put_artifact and the
    runner's gcs_uploader (SEV — gcs_uploader previously used bare ADC and ignored
    the injected SA key, 403'ing on Cloud Run where the runtime SA lacks bucket IAM)."""
    import json

    from google.cloud import storage  # lazy: only needed when GCS configured

    if settings.storage_emulator_host:
        os.environ.setdefault("STORAGE_EMULATOR_HOST", settings.storage_emulator_host)
        return storage.Client()
    if settings.google_credentials_b64:
        # Modal / Cloud Run: SA key injected as single-line base64 (no file on disk).
        import base64

        return storage.Client.from_service_account_info(
            json.loads(base64.b64decode(settings.google_credentials_b64))
        )
    if settings.google_credentials_json:
        return storage.Client.from_service_account_info(
            json.loads(settings.google_credentials_json)
        )
    if settings.google_credentials_file:
        # Local: explicit SA key file (.env isn't exported to os.environ for ADC).
        return storage.Client.from_service_account_json(settings.google_credentials_file)
    return storage.Client()  # ADC fallback


def _upload_gcs(session_id: str, job_id: str, name: str, data: bytes, content_type: str) -> str:
    client = _gcs_client()
    path = f"{session_id}/{job_id}/{name}"
    bucket = client.bucket(settings.gcs_bucket)
    bucket.blob(path).upload_from_string(data, content_type=content_type)
    # Browser-loadable public URL (bucket is public-read for the demo). The local-disk
    # fallback returns a relative /artifacts/... path; the web client handles both.
    return f"https://storage.googleapis.com/{settings.gcs_bucket}/{path}"


# ---- transcript (chat history; written by agent log_transcript hook) ----

def _transcript_key(sid: str) -> str:
    return f"session:{sid}:transcript"


async def append_message(m: Message) -> str:
    r = get_redis()
    return await r.xadd(_transcript_key(m.session_id), {"data": m.model_dump_json()})


async def read_transcript(sid: str, start: str = "-", end: str = "+") -> list[Message]:
    r = get_redis()
    rows = await r.xrange(_transcript_key(sid), start, end)
    return [Message.model_validate_json(v["data"]) for _, v in rows]


# ---- dispatch queue (sub-agent jobs awaiting a Modal spawn) -------------

DISPATCH_QUEUE = "dispatch:queue"


async def enqueue_dispatch(child_job_id: str) -> str:
    r = get_redis()
    return await r.xadd(DISPATCH_QUEUE, {"job_id": child_job_id})


# ---- chat inbox (user follow-up turns awaiting an agent reply) ----------

CHAT_INBOX = "chat:inbox"


async def enqueue_chat(session_id: str, content: str) -> str:
    """A user follow-up turn for the conversational agent (or local-sim) to answer."""
    return await get_redis().xadd(
        CHAT_INBOX, {"session_id": session_id, "content": content}
    )


# The pending chat message for a session's next agent turn. The chat_loop sets it
# right before re-spawning the lead agent; /internal/bootstrap pops it so that turn
# answers it (and a bootstrap retry can't re-answer). TTL guards against a spawn
# that never boots leaving a stale message behind.
_PENDING_CHAT_TTL = 6 * 3600


def _pending_chat_key(sid: str) -> str:
    return f"session:{sid}:pending_chat"


async def set_pending_chat(session_id: str, content: str) -> None:
    await get_redis().set(_pending_chat_key(session_id), content, ex=_PENDING_CHAT_TTL)


async def get_pending_chat(session_id: str) -> str | None:
    return await get_redis().get(_pending_chat_key(session_id))


async def pop_pending_chat(session_id: str) -> str | None:
    r = get_redis()
    async with r.pipeline(transaction=True) as p:
        p.get(_pending_chat_key(session_id))
        p.delete(_pending_chat_key(session_id))
        content, _ = await p.execute()
    return content


# ---- generic stream read / ack -----------------------------------------

async def read_stream(
    stream: str, last_id: str = "0", count: int = 10, block_ms: int = 5000
) -> list[tuple[str, dict]]:
    r = get_redis()
    res = await r.xread({stream: last_id}, count=count, block=block_ms or None)
    out: list[tuple[str, dict]] = []
    for _stream, entries in res or []:
        for entry_id, fields in entries:
            out.append((entry_id, fields))
    return out


async def ack_stream(stream: str, group: str, entry_id: str) -> None:
    """No-op unless a consumer group exists. Kept for call-site parity so a later
    migration to XREADGROUP+XACK (horizontal scale) needs no caller changes."""
    return None


async def delete_stream_entry(stream: str, entry_id: str) -> int:
    return await get_redis().xdel(stream, entry_id)


# ---- parent <-> child linkage + child status rollup --------------------

async def link_child(parent_jid: str, child_jid: str, session_id: str) -> None:
    r = get_redis()
    async with r.pipeline(transaction=True) as p:
        p.sadd(_children_key(parent_jid), child_jid)
        p.sadd(_session_jobs_key(session_id), child_jid)
        await p.execute()


async def child_statuses(parent_jid: str) -> list[dict]:
    """One row per child: {job_id, status, done, summary, metrics}. ``done`` means
    a RunResult exists (the runner writes one for both success and failure)."""
    r = get_redis()
    cids = sorted(await r.smembers(_children_key(parent_jid)))
    out: list[dict] = []
    for cjid in cids:
        job = await get_job(cjid)
        if job is None:
            continue
        run = await get_run(cjid)
        out.append({
            "job_id": cjid,
            "status": job.status.value,
            "done": run is not None,
            "summary": run.summary if run else None,
            "metrics": run.metrics if run else {},
        })
    return out


# ---- status index (runner reconciliation) ------------------------------

async def list_jobs_by_status(status: JobStatus | str) -> list[Job]:
    r = get_redis()
    ids = await r.smembers(_status_set_key(status))
    out: list[Job] = []
    for jid in ids:
        j = await get_job(jid)
        if j is not None:
            out.append(j)
    return out


# ---- artifact <-> job linkage ------------------------------------------

def _artifacts_key(jid: str) -> str:
    return f"job:{jid}:artifacts"


def deterministic_artifact_id(session_id: str, job_id: str, filename: str) -> str:
    """Content-address an artifact by its logical location (SEV-10). A reconcile
    retry that re-uploads the same blob re-derives the SAME id, so JSON.SET +
    SADD are idempotent instead of minting a duplicate ArtifactRef each pass."""
    h = hashlib.sha1(f"{session_id}/{job_id}/{filename}".encode()).hexdigest()[:12]
    return f"a_{h}"


async def link_artifact_to_job(job_id: str, artifact_id: str) -> None:
    await get_redis().sadd(_artifacts_key(job_id), artifact_id)


async def list_artifacts_for(job_id: str) -> list[ArtifactRef]:
    r = get_redis()
    aids = sorted(await r.smembers(_artifacts_key(job_id)))
    out: list[ArtifactRef] = []
    for aid in aids:
        doc = await r.json().get(f"artifact:{aid}")
        if doc:
            out.append(ArtifactRef.model_validate(doc))
    return out


# ---- session listing (sidebar chat history) ----------------------------

async def list_user_sessions(user_id: str, limit: int = 100) -> list[Session]:
    """All sessions owned by a user, newest first. Scans the bare session:* keys
    (skipping session:{sid}:events/budget/...). Fine at demo scale."""
    r = get_redis()
    out: list[Session] = []
    async for k in r.scan_iter("session:*", count=200):
        if k.count(":") != 1:  # skip session:{sid}:events / :budget / :transcript / ...
            continue
        doc = await r.json().get(k)
        if doc and doc.get("user_id") == user_id:
            out.append(Session.model_validate(doc))
    out.sort(key=lambda s: s.created_at, reverse=True)
    return out[:limit]


# ---- full session read (chat resume endpoint) --------------------------

async def read_full_session(sid: str) -> dict:
    r = get_redis()
    session_doc = await r.json().get(_session_key(sid))
    job_ids = list(await r.smembers(_session_jobs_key(sid)))
    jobs: list[dict] = []
    runs: list[dict] = []
    tree: dict[str, list[str]] = {}
    artifacts: list[dict] = []
    for jid in sorted(job_ids):
        j = await get_job(jid)
        if j:
            jobs.append(j.model_dump(mode="json"))
        rn = await get_run(jid)
        if rn:
            runs.append(rn.model_dump(mode="json"))
        kids = sorted(await r.smembers(_children_key(jid)))
        if kids:
            tree[jid] = kids
        artifacts.extend(a.model_dump(mode="json") for a in await list_artifacts_for(jid))
    transcript = [m.model_dump(mode="json") for m in await read_transcript(sid)]
    # Autonomous sessions carry a Loop record; oneshot sessions have none (null).
    # The UI seeds its loop view from this so a reload shows round/status before the
    # event stream replays.
    loop = await get_loop(sid)
    return {
        "session": session_doc,
        "jobs": jobs,
        "runs": runs,
        "tree": tree,
        "transcript": transcript,
        "artifacts": artifacts,
        "loop": loop.model_dump(mode="json") if loop else None,
    }


# ---- per-session ephemeral agent token (SEV-4) -------------------------
#
# A single shared ALPHA_INTERNAL_TOKEN is total-compromise: one leak (a log line,
# a malicious sub-agent reading env via Bash) lets an attacker drive /internal/*
# against ANY session. Instead the runner mints a per-session token at spawn,
# injects it as a per-execution env override, and /internal/* resolves it back to
# the owning session_id — so a token can only ever act on its own session.

AGENT_TOKEN_TTL = 24 * 3600  # outlives a 4h main-agent + a late 2h sub-agent


def _agent_token_key(token: str) -> str:
    return f"agent_token:{token}"


def _session_token_key(sid: str) -> str:
    return f"session:{sid}:agent_token"


async def mint_agent_token(session_id: str, ttl: int = AGENT_TOKEN_TTL) -> str:
    token = secrets.token_urlsafe(32)
    r = get_redis()
    async with r.pipeline(transaction=True) as p:
        p.set(_agent_token_key(token), session_id, ex=ttl)
        p.set(_session_token_key(session_id), token, ex=ttl)
        await p.execute()
    return token


async def get_session_token(session_id: str, ttl: int = AGENT_TOKEN_TTL) -> str:
    """Return the session's live token, minting one on first use (idempotent so a
    sub-agent spawn reuses the same token the main-agent spawn already minted)."""
    existing = await get_redis().get(_session_token_key(session_id))
    if existing:
        return existing
    return await mint_agent_token(session_id, ttl)


async def resolve_agent_token(token: str | None) -> str | None:
    """Map a bearer token back to the session it was minted for, or None."""
    if not token:
        return None
    return await get_redis().get(_agent_token_key(token))


async def revoke_session_token(session_id: str) -> None:
    r = get_redis()
    token = await r.get(_session_token_key(session_id))
    async with r.pipeline(transaction=True) as p:
        if token:
            p.delete(_agent_token_key(token))
        p.delete(_session_token_key(session_id))
        await p.execute()


# ---- runner leader lease (SEV-2) ---------------------------------------
#
# --max-instances=1 does NOT prevent two runners briefly overlapping during a
# rolling deploy; both would XREAD the same queues and double-spawn. A short Redis
# lease elects exactly one leader; loops abort each iteration if they don't own it.

LEADER_KEY = "runner:leader"
LEADER_TTL = 15

# CAS scripts: only the current owner may extend or release the lease. Both the
# re-acquire and release paths MUST be atomic — a GET-then-SET/DEL would let a laggy
# instance stamp/delete a lease a newer leader just took (electing two leaders).
_LEASE_REFRESH_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2])
else
  return false
end
"""
_LEASE_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
else
  return 0
end
"""


async def acquire_leader_lease(runner_id: str, ttl: int = LEADER_TTL) -> bool:
    r = get_redis()
    if await r.set(LEADER_KEY, runner_id, nx=True, ex=ttl):
        return True
    # Already held — extend ONLY if still ours, atomically (SEV-2: no TOCTOU that
    # could return True for us while the key already names a newer leader).
    return await refresh_leader_lease(runner_id, ttl)


async def refresh_leader_lease(runner_id: str, ttl: int = LEADER_TTL) -> bool:
    res = await get_redis().eval(_LEASE_REFRESH_LUA, 1, LEADER_KEY, runner_id, ttl)
    return bool(res)


async def release_leader_lease(runner_id: str) -> None:
    await get_redis().eval(_LEASE_RELEASE_LUA, 1, LEADER_KEY, runner_id)


__all__ = [
    "get_redis", "ping", "new_id", "create_session", "get_session", "read_state",
    "create_job", "get_job", "update_job", "set_job_status", "get_children",
    "get_session_jobs", "get_root_job",
    "write_run", "get_run", "get_children_runs", "decr_budget", "incr_budget",
    "emit_event", "tail_events", "enqueue_session", "put_artifact",
    "claim_fanout", "release_fanout", "SESSIONS_QUEUE",
    # v2 additions
    "append_message", "read_transcript",
    "DISPATCH_QUEUE", "enqueue_dispatch", "read_stream", "ack_stream",
    "delete_stream_entry",
    "link_child", "child_statuses", "list_jobs_by_status",
    "deterministic_artifact_id", "link_artifact_to_job", "list_artifacts_for",
    "read_full_session",
    "mint_agent_token", "get_session_token", "resolve_agent_token",
    "revoke_session_token", "AGENT_TOKEN_TTL",
    "acquire_leader_lease", "refresh_leader_lease", "release_leader_lease",
    "LEADER_KEY", "LEADER_TTL",
]
