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
import time

import sentry_sdk

from infra import loop_policy, store
from infra.observability import tag_alpha
from infra.schemas import (
    EventEnvelope,
    EventType,
    Job,
    JobKind,
    JobStatus,
    LoopStatus,
    RoundRecord,
    RunResult,
)
from runner.cloud_run_client import fetch_exec_logs, poll_cloud_run_exec, spawn_main_agent_job
from runner.modal_client import (
    cancel_modal_call,
    poll_modal_call,
    spawn_sub_agent,
)

POLL_INTERVAL = 2.0
RECONCILE_INTERVAL = 5.0
LEADERSHIP_INTERVAL = 5.0
CLEANUP_GRACE_SECONDS = 60.0  # wait this long after a session goes terminal before reclaiming
# Idea 3 (synthesis barrier): a depth-0 main agent can exit `done` while its sub-agents
# are still training (their wall-clock >> the agent's synthesis turn). We hold the depth-0
# job in `running` until its children are terminal, so late results (e.g. a slow ICM run)
# land + get recorded instead of being cancelled mid-flight. This is the backstop cap on
# that hold — a child can't outlive the Modal sub-agent timeout (2h), so once we pass it a
# still-"running" child is wedged and we finalize + reap anyway.
DEPTH0_BARRIER_GRACE_SECONDS = 3600.0 * 2 + 300.0

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
        with sentry_sdk.start_transaction(
            op="alpha.runner.spawn_main_agent", name="spawn_main_agent"
        ) as txn:
            tag_alpha(txn, session_id=sid, job_id=root_id, depth=0, backend="cloud_run_job")
            traceparent = sentry_sdk.get_traceparent() or ""
            baggage = sentry_sdk.get_baggage() or ""
            try:
                sandbox_id = await spawn_main_agent_job(  # may raise (SEV-9) -> no xdel
                    sid, root_id, traceparent=traceparent, baggage=baggage)
            except Exception as e:  # noqa: BLE001
                txn.set_status("internal_error")
                sentry_sdk.capture_exception(e)
                print(f"[session_loop] spawn failed for {root_id}: {e!r}")
                continue
            txn.set_tag("alpha.sandbox_id", sandbox_id)
            # Atomic: status+sandbox_id+backend in one txn so a crash never strands the
            # job as queued-with-a-live-sandbox.
            await store.mark_job_running(root_id, sandbox_id, "cloud_run_job")
            await _emit(sid, root_id, 0, EventType.status, {"status": "running", "sandbox": sandbox_id})
            # Round 1 of an autonomous loop: emit round_started here so the UI shows
            # "Round 1 / N" from the start. Rounds 2+ are announced by _advance_loop
            # before re-enqueue, so only emit when no round has been recorded yet.
            loop = await store.get_loop(sid)
            if loop is not None and not loop.rounds:
                await _emit(sid, root_id, 0, EventType.status,
                            {"phase": "round_started", "round_index": 1,
                             "max_rounds": loop.max_rounds, "goal_metric": loop.goal_metric})
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
        with sentry_sdk.start_transaction(
            op="alpha.runner.spawn_sub_agent", name="spawn_sub_agent"
        ) as txn:
            tag_alpha(txn, session_id=job.session_id, job_id=jid, depth=job.depth,
                      job_kind=job.kind.value, backend="modal")
            traceparent = sentry_sdk.get_traceparent() or ""
            baggage = sentry_sdk.get_baggage() or ""
            try:
                # PR2: the dispatch record rides as a Modal call arg (no shared volume) —
                # the sub_agent function writes it into its own /workspace/.dispatched on boot.
                sandbox_id = await spawn_sub_agent(
                    jid, job.session_id, _record_from_job(job),
                    traceparent=traceparent, baggage=baggage)
            except Exception as e:  # noqa: BLE001
                txn.set_status("internal_error")
                sentry_sdk.capture_exception(e)
                print(f"[dispatch_loop] spawn failed for {jid}: {e!r}")
                continue
            txn.set_tag("alpha.sandbox_id", sandbox_id)
            await store.mark_job_running(jid, sandbox_id, "modal")  # atomic stamp (see above)
            p = job.params or {}
            await _emit(job.session_id, jid, job.depth, EventType.spawn,
                        {"sandbox": sandbox_id, "kind": job.kind.value,
                         "goal": p.get("goal"), "strategy": p.get("strategy")})
            await r.xdel(store.DISPATCH_QUEUE, entry_id)  # SEV-1


# ---- reconcile_loop ----------------------------------------------------

async def _poll(job) -> str:
    if job.backend == "cloud_run_job":
        return await poll_cloud_run_exec(job.sandbox_id)
    return await poll_modal_call(job.sandbox_id)


async def _finalize_done(job) -> None:
    """The sandbox finished.

    PR2: a sub-agent (depth>=1) pushes its result + artifacts to POST /internal/result,
    which records the RunResult and flips job status BEFORE the Modal call returns. So
    normally the job is already terminal by the time we'd reconcile it. If we get here
    with the job still running, the push must have NOT happened (the sub-agent crashed or
    its finalize hook failed to POST) -> fail it. The main agent (depth 0) has no
    structured result, so we just mark it done."""
    sid, jid = job.session_id, job.id
    if job.depth >= 1:
        run = await store.get_run(jid)
        if run is None:
            await _finalize_failed(job, reason="sub-agent exited without posting a result")
            return
        failed = (run.status or "done").lower() == "failed"
        await store.set_job_status(jid, JobStatus.failed if failed else JobStatus.done)
        await _emit(sid, jid, job.depth, EventType.summary,
                    {"summary": (run.summary or "")[:240], "metrics": run.metrics,
                     "reported_status": run.status})
        if failed:  # SEV-8: a failed parent orphans its children
            await _cancel_orphans_if_terminal(job)
        return

    # depth 0 (main agent): no structured result to read.
    # Synthesis barrier (idea 3): don't finalize — and so don't cancel orphans (idea 4) —
    # while sub-agents are still running, within a grace cap. The main agent's process is
    # already gone; holding its job status `running` simply keeps the session open so late
    # children finish and are recorded instead of being reaped half-trained.
    if not await _children_settled(job):
        return  # leave running; reconcile revisits next pass

    await store.write_run(RunResult(job_id=jid, status="done", summary=""))
    await store.set_job_status(jid, JobStatus.done)
    await _emit(sid, jid, 0, EventType.summary, {"summary": "", "metrics": {}})
    # Idea 4: now that depth-0 is terminal, reap any straggler child that outlived the
    # grace cap (oneshot main agent exiting `done` left them uncancelled before).
    await _cancel_orphans_if_terminal(job)
    await _advance_loop(job)  # autonomous sessions: maybe spawn the next round


# ---- autonomous loop advancement (v1.5) --------------------------------

async def _advance_loop(job) -> None:
    """A round (depth-0 agent) just finished. For an autonomous session, apply the
    stop policy and either spawn the next round or mark the loop terminal. This is
    what gives the loop its OWN terminal state, distinct from any single job's."""
    sid = job.session_id
    session = await store.get_session(sid)
    if session is None or session.mode != "autonomous":
        return
    loop = await store.get_loop(sid)
    if loop is None or loop.status != LoopStatus.running:
        return

    # Backstop: ensure this finished round is counted even if the agent crashed before
    # POSTing /internal/loop/round — otherwise len(rounds) never grows and max_rounds
    # can't fire (only budget could), risking a runaway loop.
    if not any(r.job_id == job.id for r in loop.rounds):
        await store.append_round(sid, RoundRecord(
            round_index=len(loop.rounds) + 1, job_id=job.id, best_metric=None,
            summary="(round exited without a report)"))
        loop = await store.get_loop(sid)

    r = store.get_redis()
    budget_raw = await r.get(store._budget_key(sid))
    budget = int(budget_raw) if budget_raw is not None else 0

    decision = loop_policy.decide(loop, budget)
    if decision.action == "stop":
        await store.set_loop_status(sid, decision.status, decision.reason)
        await _emit(sid, job.id, 0, EventType.status,
                    {"phase": "loop_stopped", "status": decision.status.value,
                     "reason": decision.reason, "round_index": len(loop.rounds),
                     "max_rounds": loop.max_rounds, "goal_metric": loop.goal_metric})
        return

    # continue: create + enqueue the next round's depth-0 agent execution.
    next_round = len(loop.rounds) + 1
    new_id = store.new_id("j")
    await store.create_job(Job(
        id=new_id, session_id=sid, depth=0, kind=JobKind.agent,
        params={"goal": session.goal}, status=JobStatus.queued, backend="cloud_run_job"))
    await store.set_loop_current_job(sid, new_id)
    # Re-point the session root so session_loop spawns THIS round's job (not round 1's).
    await r.json().set(store._session_key(sid), "$.root_job_id", new_id)
    await store.enqueue_session(sid)
    await _emit(sid, new_id, 0, EventType.status,
                {"phase": "round_started", "round_index": next_round,
                 "max_rounds": loop.max_rounds, "goal_metric": loop.goal_metric})


async def _finalize_failed(job, reason: str = "sandbox died") -> None:
    sid, jid = job.session_id, job.id
    await store.write_run(RunResult(job_id=jid, status="failed", summary=reason))
    await store.set_job_status(jid, JobStatus.failed)
    await _emit(sid, jid, job.depth, EventType.status, {"status": "failed", "reason": reason})
    # Surface the gcloud (Cloud Run Job) execution's log tail to chat so the user sees
    # WHY the main agent died — otherwise a failed depth-0 job is opaque past "failed".
    if job.backend == "cloud_run_job" and job.sandbox_id:
        log_tail = await fetch_exec_logs(job.sandbox_id)
        if log_tail:
            await _emit(sid, jid, job.depth, EventType.error,
                        {"reason": reason, "source": "cloud_run_logs", "lines": log_tail})
    await _cancel_orphans_if_terminal(job)
    # A failed depth-0 round must still advance the loop — otherwise an OOM/timeout
    # leaves loop status=running forever (no next round spawned, never reclaimed).
    # The round is counted (backstop) and the policy retries or stops on max_rounds.
    if job.depth == 0:
        await _advance_loop(job)


async def _children_settled(job) -> bool:
    """True when every child of a depth-0 job is terminal — OR the barrier grace cap has
    elapsed since the parent first finished (backstop against a child wedged in `running`,
    which the Modal timeout makes impossible to exceed in reality). While it returns False
    the depth-0 job stays `running` and reconcile revisits it, giving slow sub-agents time
    to land before synthesis/cleanup treats the round as closed."""
    children = [await store.get_job(cjid) for cjid in await store.get_children(job.id)]
    pending = [c for c in children if c is not None and c.status not in _TERMINAL]
    if not pending:
        return True
    r = store.get_redis()
    key = f"job:{job.id}:done_since"
    now = time.time()
    await r.set(key, now, nx=True, ex=7 * 24 * 3600)  # stamp first-finished once
    first = await r.get(key)
    return first is not None and (now - float(first)) >= DEPTH0_BARRIER_GRACE_SECONDS


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
            sentry_sdk.add_breadcrumb(category="alpha.poll", level="warning",
                                      message=f"poll failed for {job.id}: {e!r}")
            print(f"[reconcile] poll failed for {job.id}: {e!r}")
            continue
        if state in ("done", "failed"):
            with sentry_sdk.start_transaction(
                op="alpha.runner.reconcile", name=f"reconcile/{job.backend}"
            ) as txn:
                tag_alpha(txn, session_id=job.session_id, job_id=job.id,
                          depth=job.depth, backend=job.backend)
                txn.set_tag("alpha.poll_state", state)
                if state == "done":
                    await _finalize_done(job)
                else:
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
        # An autonomous loop is "between rounds" when its round job is momentarily
        # terminal but the loop isn't. Never reclaim (revoke the token) until the loop
        # itself reaches a terminal status — otherwise the next round would 401.
        loop = await store.get_loop(sid)
        if loop is not None and loop.status == LoopStatus.running:
            continue
        # Grace window: stamp the first-terminal time, and only do the irreversible
        # cleanup once it's been terminal for CLEANUP_GRACE_SECONDS — so a late
        # finalize-hook push isn't 401'd by a just-revoked token.
        ts_key = f"session:{sid}:terminal_since"
        await r.set(ts_key, now, nx=True, ex=7 * 24 * 3600)
        first = await r.get(ts_key)
        if first is not None and (now - float(first)) < CLEANUP_GRACE_SECONDS:
            continue
        # SET NX flag: revoke the session token exactly once. (PR2: no per-session
        # Modal volume to reclaim anymore — results come back over HTTP.)
        if await r.set(f"session:{sid}:cleaned", "1", nx=True, ex=7 * 24 * 3600):
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
