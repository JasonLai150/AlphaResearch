"""The runner's asyncio loops.

Three loops, each leader-gated (SEV-2) so exactly one runner acts even during a
rolling deploy:

  * session_loop   — drain sessions:queue → spawn main-agent Cloud Run Job
  * dispatch_loop  — drain dispatch:queue → spawn sub-agent Modal Function
  * reconcile_loop — poll running jobs → finalize, ship artifacts, cancel orphans,
                     reclaim terminal-session volumes

There is NO volume_watch_loop: in the Cloud Run architecture the main-agent has no
shared filesystem with the runner, so child jobs are registered via POST
/internal/dispatch (runner.internal_api), not by scanning a shared volume.

Spawn idempotency (SEV-1): every spawn is gated on the job still being
pending/queued with no sandbox_id, and the queue entry is XDEL'd only AFTER a
successful spawn — a spawn that raises leaves the entry for the next pass.
"""

from __future__ import annotations

import asyncio
import json
import time

from infra import store
from infra.schemas import EventEnvelope, EventType, JobStatus, RunResult
from runner.cloud_run_client import poll_cloud_run_exec, spawn_main_agent_job
from runner.gcs_uploader import upload_artifacts
from runner.modal_client import (
    artifacts_dir,
    cancel_modal_call,
    delete_session_volume,
    poll_modal_call,
    reload_volume,
    result_done_sentinel,
    results_for,
    spawn_sub_agent,
    write_dispatch_record,
)

POLL_INTERVAL = 2.0
RECONCILE_INTERVAL = 5.0
LEADERSHIP_INTERVAL = 5.0
CLEANUP_GRACE_SECONDS = 60.0  # wait this long after a session goes terminal before reclaiming

_TERMINAL = {JobStatus.done, JobStatus.failed, JobStatus.cancelled}
_SPAWNABLE = {JobStatus.pending, JobStatus.queued}


# ---- leadership (SEV-2) -------------------------------------------------

class _Leader:
    runner_id: str = ""
    is_leader: bool = False


_leader = _Leader()


async def leadership_loop(runner_id: str, interval: float = LEADERSHIP_INTERVAL) -> None:
    _leader.runner_id = runner_id
    while True:
        try:
            _leader.is_leader = await store.acquire_leader_lease(runner_id, ttl=store.LEADER_TTL)
        except Exception as e:  # noqa: BLE001
            _leader.is_leader = False
            print(f"[leadership_loop] {e!r}")
        await asyncio.sleep(interval)


# ---- helpers -----------------------------------------------------------

async def _emit(session_id: str, job_id: str, depth: int, type_: EventType, payload: dict) -> None:
    await store.emit_event(EventEnvelope(
        session_id=session_id, job_id=job_id, depth=depth, type=type_, payload=payload,
    ))


async def _root_job_id(sid: str) -> str | None:
    r = store.get_redis()
    doc = await r.json().get(store._session_key(sid))
    if doc and doc.get("root_job_id"):
        return doc["root_job_id"]
    for jid in await store.get_session_jobs(sid):  # fallback: scan for the depth-0 job
        j = await store.get_job(jid)
        if j and j.depth == 0:
            return jid
    return None


def _record_from_job(job) -> dict:
    p = job.params or {}
    return {
        "job_id": job.id,
        "parent_job_id": job.parent_job_id,
        "session_id": job.session_id,
        "depth": job.depth,
        "kind": job.kind.value,
        "plan": p.get("plan"),
        "idea_id": p.get("idea_id"),
        "strategy": p.get("strategy"),
        "created_at": job.created_at,
    }


# ---- session_loop: spawn main-agent Cloud Run Jobs ---------------------

async def _consume_sessions_once() -> None:
    r = store.get_redis()
    for entry_id, fields in await store.read_stream(store.SESSIONS_QUEUE, "0", 50, 0):
        sid = fields.get("session_id")
        root_id = await _root_job_id(sid) if sid else None
        if not root_id:
            await r.xdel(store.SESSIONS_QUEUE, entry_id)  # nothing to spawn; drop
            continue
        job = await store.get_job(root_id)
        if job is None or job.status not in _SPAWNABLE or job.sandbox_id:
            await r.xdel(store.SESSIONS_QUEUE, entry_id)  # SEV-1: already spawned/terminal
            continue
        try:
            sandbox_id = await spawn_main_agent_job(sid, root_id)  # may raise (SEV-9) -> no xdel
        except Exception as e:  # noqa: BLE001
            print(f"[session_loop] spawn failed for {root_id}: {e!r}")
            continue
        # Atomic: status+sandbox_id+backend in one txn so a crash never strands the
        # job as queued-with-a-live-sandbox.
        await store.mark_job_running(root_id, sandbox_id, "cloud_run_job")
        await _emit(sid, root_id, 0, EventType.status, {"status": "running", "sandbox": sandbox_id})
        await r.xdel(store.SESSIONS_QUEUE, entry_id)  # SEV-1: xdel only after success


# ---- dispatch_loop: spawn sub-agent Modal Functions --------------------

async def _consume_dispatches_once() -> None:
    r = store.get_redis()
    for entry_id, fields in await store.read_stream(store.DISPATCH_QUEUE, "0", 50, 0):
        jid = fields.get("job_id")
        job = await store.get_job(jid) if jid else None
        if job is None or job.status not in _SPAWNABLE or job.sandbox_id:
            await r.xdel(store.DISPATCH_QUEUE, entry_id)  # SEV-1
            continue
        try:
            write_dispatch_record(job.session_id, jid, _record_from_job(job))
            sandbox_id = await spawn_sub_agent(jid, job.session_id)
        except Exception as e:  # noqa: BLE001
            print(f"[dispatch_loop] spawn failed for {jid}: {e!r}")
            continue
        await store.mark_job_running(jid, sandbox_id, "modal")  # atomic stamp (see above)
        await _emit(job.session_id, jid, job.depth, EventType.spawn,
                    {"sandbox": sandbox_id, "kind": job.kind.value})
        await r.xdel(store.DISPATCH_QUEUE, entry_id)  # SEV-1


# ---- reconcile_loop ----------------------------------------------------

async def _poll(job) -> str:
    if job.backend == "cloud_run_job":
        return await poll_cloud_run_exec(job.sandbox_id)
    return await poll_modal_call(job.sandbox_id)


async def _finalize_done(job) -> None:
    """The sandbox finished. For a sub-agent, honor its self-reported status from
    result.json (a sub-agent that exited cleanly but reports status='failed' must NOT
    be recorded as a success). The main agent (depth 0) has no structured result."""
    sid, jid = job.session_id, job.id
    summary, metrics, reported = "", {}, "done"
    if job.depth >= 1:
        await reload_volume(sid)
        result_path, _ = results_for(sid, jid)
        if not result_done_sentinel(sid, jid).exists():
            # SEV-7: completed but no fully-written result -> failed, not silent empty done.
            await _finalize_failed(job, reason="completed without result sentinel")
            return
        try:
            payload = json.loads(result_path.read_text())
        except (json.JSONDecodeError, OSError):
            await _finalize_failed(job, reason="result.json present but unreadable/invalid")
            return
        summary = payload.get("summary", "")
        metrics = payload.get("metrics", {}) or {}
        reported = (payload.get("status") or "done").lower()

    artifacts = await upload_artifacts(sid, jid, artifacts_dir(sid, jid))  # SEV-10 idempotent
    failed = reported == "failed"
    run_status = "failed" if failed else reported  # done | partial | failed
    job_status = JobStatus.failed if failed else JobStatus.done
    await store.write_run(
        RunResult(job_id=jid, status=run_status, summary=summary, metrics=metrics))
    await store.set_job_status(jid, job_status)
    await _emit(sid, jid, job.depth, EventType.summary,
                {"summary": summary[:240], "metrics": metrics,
                 "artifact_count": len(artifacts), "reported_status": reported})
    # Only a FAILED/terminal parent orphans children (SEV-8). On a graceful success we
    # leave any still-running children alone — they finalize independently via reconcile.
    if failed:
        await _cancel_orphans_if_terminal(job)


async def _finalize_failed(job, reason: str = "sandbox died") -> None:
    sid, jid = job.session_id, job.id
    _, failed_path = results_for(sid, jid)
    try:
        failed_path.parent.mkdir(parents=True, exist_ok=True)
        failed_path.write_text(json.dumps({"job_id": jid, "status": "failed", "reason": reason}))
    except OSError:
        pass
    await store.write_run(RunResult(job_id=jid, status="failed", summary=reason))
    await store.set_job_status(jid, JobStatus.failed)
    await _emit(sid, jid, job.depth, EventType.status, {"status": "failed", "reason": reason})
    await _cancel_orphans_if_terminal(job)


async def _cancel_orphans_if_terminal(job) -> None:
    """SEV-8: when a parent terminates (e.g. main-agent hits the Cloud Run 4h cap),
    cancel its still-running children so they don't keep writing to a ghost parent."""
    for cjid in await store.get_children(job.id):
        child = await store.get_job(cjid)
        if child is None or child.status in _TERMINAL:
            continue
        if child.sandbox_id and child.backend == "modal":
            await cancel_modal_call(child.sandbox_id)
        await store.set_job_status(cjid, JobStatus.cancelled)
        await _emit(child.session_id, cjid, child.depth, EventType.status,
                    {"status": "cancelled", "reason": f"parent {job.id} terminal"})


async def _reconcile_once() -> None:
    for stale in await store.list_jobs_by_status(JobStatus.running):
        job = await store.get_job(stale.id)  # SEV-12: re-fetch (status may have changed)
        if job is None or job.status != JobStatus.running or not job.sandbox_id:
            continue
        try:
            state = await _poll(job)
        except Exception as e:  # noqa: BLE001
            print(f"[reconcile] poll failed for {job.id}: {e!r}")
            continue
        if state == "done":
            await _finalize_done(job)
        elif state == "failed":
            await _finalize_failed(job)
    await _cleanup_terminal_sessions()


# ---- terminal-session cleanup (SEV-6) ----------------------------------

async def _active_sessions() -> list[str]:
    r = store.get_redis()
    out: list[str] = []
    async for k in r.scan_iter("session:*", count=200):
        if k.count(":") == 1:  # bare "session:{sid}", not session:{sid}:events etc.
            out.append(k.split(":", 1)[1])
    return out


async def _session_fully_terminal(sid: str) -> bool:
    jids = await store.get_session_jobs(sid)
    if not jids:
        return False
    for jid in jids:
        j = await store.get_job(jid)
        if j is None or j.status not in _TERMINAL:
            return False
    return True


async def _cleanup_terminal_sessions() -> None:
    r = store.get_redis()
    now = time.time()
    for sid in await _active_sessions():
        if not await _session_fully_terminal(sid):
            continue
        # Grace window: stamp the first-terminal time, and only do the irreversible
        # cleanup once it's been terminal for CLEANUP_GRACE_SECONDS — so a late
        # finalize-hook push isn't 401'd by a just-revoked token.
        ts_key = f"session:{sid}:terminal_since"
        await r.set(ts_key, now, nx=True, ex=7 * 24 * 3600)
        first = await r.get(ts_key)
        if first is not None and (now - float(first)) < CLEANUP_GRACE_SECONDS:
            continue
        # SET NX flag: do the volume delete + token revoke exactly once.
        if await r.set(f"session:{sid}:cleaned", "1", nx=True, ex=7 * 24 * 3600):
            await delete_session_volume(sid)
            await store.revoke_session_token(sid)
            await _emit(sid, "", 0, EventType.status, {"status": "session_cleaned"})


# ---- loop runners (leader-gated) ---------------------------------------

async def session_loop() -> None:
    while True:
        try:
            if _leader.is_leader:
                await _consume_sessions_once()
        except Exception as e:  # noqa: BLE001
            print(f"[session_loop] {e!r}")
        await asyncio.sleep(POLL_INTERVAL)


async def dispatch_loop() -> None:
    while True:
        try:
            if _leader.is_leader:
                await _consume_dispatches_once()
        except Exception as e:  # noqa: BLE001
            print(f"[dispatch_loop] {e!r}")
        await asyncio.sleep(POLL_INTERVAL)


async def reconcile_loop() -> None:
    while True:
        try:
            if _leader.is_leader:
                await _reconcile_once()
        except Exception as e:  # noqa: BLE001
            print(f"[reconcile_loop] {e!r}")
        await asyncio.sleep(RECONCILE_INTERVAL)
