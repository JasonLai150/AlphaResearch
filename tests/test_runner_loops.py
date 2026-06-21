"""Runner loops: spawn gating (SEV-1), reconcile re-fetch (SEV-12), result handling
(PR2: read the pushed RunResult from Redis), orphan cancellation (SEV-8),
terminal-session cleanup (SEV-6). Modal + Cloud Run spawns/polls are mocked."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from infra import store
from infra.schemas import Job, JobKind, JobStatus, RunResult
from runner import loops

pytestmark = pytest.mark.asyncio


async def _seed_session(sid="s_a"):
    await store.create_session(sid, "u_1", "explore", 100)


async def _seed_root(sid="s_a", jid="j_root", status=JobStatus.queued, sandbox_id=None,
                     backend="modal"):
    await store.create_job(Job(id=jid, session_id=sid, depth=0, kind=JobKind.agent,
                               status=status, sandbox_id=sandbox_id, backend=backend))
    await store.get_redis().json().set(f"session:{sid}", "$.root_job_id", jid)


# ---- session_loop (SEV-1) ----------------------------------------------

async def test_session_loop_spawns_root_and_records_sandbox(fake_redis):
    await _seed_session()
    await _seed_root()
    await store.enqueue_session("s_a")
    spawn = AsyncMock(return_value="exec_1")
    with patch("runner.loops.spawn_main_agent_job", spawn):
        await loops._consume_sessions_once()
    spawn.assert_awaited_once()
    assert spawn.await_args.args == ("s_a", "j_root")  # OTEL trace kwargs may also be present
    j = await store.get_job("j_root")
    assert j.sandbox_id == "exec_1"
    assert j.status == JobStatus.running
    assert j.backend == "cloud_run_job"
    assert await store.read_stream(store.SESSIONS_QUEUE, "0", 10, 0) == []  # drained


async def test_session_loop_idempotent_on_already_running(fake_redis):
    """SEV-1: a re-delivered session whose root already spawned must not re-spawn."""
    await _seed_session()
    await _seed_root(status=JobStatus.running, sandbox_id="exec_old", backend="cloud_run_job")
    await store.enqueue_session("s_a")
    spawn = AsyncMock(return_value="exec_new")
    with patch("runner.loops.spawn_main_agent_job", spawn):
        await loops._consume_sessions_once()
    spawn.assert_not_awaited()
    assert (await store.get_job("j_root")).sandbox_id == "exec_old"
    assert await store.read_stream(store.SESSIONS_QUEUE, "0", 10, 0) == []  # dup dropped


async def test_session_loop_keeps_entry_on_spawn_failure(fake_redis):
    """SEV-1/SEV-9: a failed spawn must NOT xdel — it retries next pass."""
    await _seed_session()
    await _seed_root()
    await store.enqueue_session("s_a")
    spawn = AsyncMock(side_effect=RuntimeError("no execution name"))
    with patch("runner.loops.spawn_main_agent_job", spawn):
        await loops._consume_sessions_once()
    assert len(await store.read_stream(store.SESSIONS_QUEUE, "0", 10, 0)) == 1  # retained
    assert (await store.get_job("j_root")).status == JobStatus.queued  # unchanged


# ---- dispatch_loop -----------------------------------------------------

async def test_dispatch_loop_spawns_sub_agent_with_record(fake_redis):
    """PR2: the dispatch record is passed to spawn (Modal call arg), not written to a volume."""
    await _seed_session()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               kind=JobKind.agent, status=JobStatus.queued,
                               params={"plan": {"id": "p"}, "idea_id": "i",
                                       "strategy": "exploration: x"}))
    await store.enqueue_dispatch("j_c")
    spawn = AsyncMock(return_value="sb_c")
    with patch("runner.loops.spawn_sub_agent", spawn):
        await loops._consume_dispatches_once()
    spawn.assert_awaited_once()
    args = spawn.await_args.args
    assert args[0] == "j_c" and args[1] == "s_a"
    assert args[2]["idea_id"] == "i" and args[2]["plan"] == {"id": "p"}  # record passed through
    j = await store.get_job("j_c")
    assert j.sandbox_id == "sb_c" and j.status == JobStatus.running and j.backend == "modal"


# ---- reconcile: failure + success --------------------------------------

async def test_reconcile_marks_failed_on_dead_sandbox(fake_redis):
    await _seed_session()
    await store.create_job(Job(id="j_1", session_id="s_a", depth=1, status=JobStatus.running,
                               sandbox_id="sb_1", backend="modal"))
    with patch("runner.loops.poll_modal_call", AsyncMock(return_value="failed")):
        await loops._reconcile_once()
    assert (await store.get_job("j_1")).status == JobStatus.failed
    run = await store.get_run("j_1")
    assert run is not None and run.status == "failed"


async def test_reconcile_done_reads_pushed_result(fake_redis):
    """PR2: the sub-agent already POSTed its RunResult to Redis; reconcile reads it."""
    await _seed_session()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               status=JobStatus.running, sandbox_id="sb_c", backend="modal"))
    await store.write_run(RunResult(job_id="j_c", status="done", summary="ok",
                                    metrics={"r": 0.5}))
    with patch("runner.loops.poll_modal_call", AsyncMock(return_value="done")):
        await loops._reconcile_once()
    assert (await store.get_job("j_c")).status == JobStatus.done
    run = await store.get_run("j_c")
    assert run.summary == "ok" and run.metrics["r"] == 0.5


async def test_reconcile_done_without_pushed_result_fails(fake_redis):
    """PR2: Modal call done but no RunResult in Redis -> the sub-agent exited without
    posting (crash / failed hook) -> failed, not a silent empty done."""
    await _seed_session()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               status=JobStatus.running, sandbox_id="sb_c", backend="modal"))
    with patch("runner.loops.poll_modal_call", AsyncMock(return_value="done")):
        await loops._reconcile_once()
    assert (await store.get_job("j_c")).status == JobStatus.failed


async def test_reconcile_honors_subagent_self_reported_failure(fake_redis):
    """A sub-agent that pushed status='failed' must be recorded failed, not masked done."""
    await _seed_session()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               status=JobStatus.running, sandbox_id="sb_c", backend="modal"))
    await store.write_run(RunResult(job_id="j_c", status="failed",
                                    summary="diverged; no improvement"))
    with patch("runner.loops.poll_modal_call", AsyncMock(return_value="done")):
        await loops._reconcile_once()
    j = await store.get_job("j_c")
    assert j.status == JobStatus.failed
    run = await store.get_run("j_c")
    assert run.status == "failed" and "diverged" in run.summary


# ---- reconcile: SEV-8 orphan cancellation ------------------------------

async def test_reconcile_parent_terminal_cancels_children(fake_redis):
    await _seed_session()
    await store.create_job(Job(id="j_root", session_id="s_a", depth=0, status=JobStatus.running,
                               sandbox_id="exec_1", backend="cloud_run_job"))
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               status=JobStatus.running, sandbox_id="sb_c", backend="modal"))
    cancel = AsyncMock()
    with patch("runner.loops.poll_cloud_run_exec", AsyncMock(return_value="failed")), \
         patch("runner.loops.poll_modal_call", AsyncMock(return_value="running")), \
         patch("runner.loops.cancel_modal_call", cancel):
        await loops._reconcile_once()
    assert (await store.get_job("j_root")).status == JobStatus.failed
    assert (await store.get_job("j_c")).status == JobStatus.cancelled
    cancel.assert_awaited_once_with("sb_c")


# ---- depth-0 synthesis barrier (idea 3) + orphan-on-done (idea 4) ------

async def _seed_root_with_child(child_status=JobStatus.running):
    await _seed_session()
    await store.create_job(Job(id="j_root", session_id="s_a", depth=0, kind=JobKind.agent,
                               status=JobStatus.running, sandbox_id="exec_1",
                               backend="cloud_run_job"))
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               status=child_status, sandbox_id="sb_c", backend="modal"))


async def test_depth0_done_defers_while_child_running(fake_redis):
    """Idea 3: a depth-0 agent that finished `done` while a sub-agent is still training
    must NOT finalize yet — it stays `running` so the slow child can land + be recorded."""
    await _seed_root_with_child(child_status=JobStatus.running)
    cancel = AsyncMock()
    with patch("runner.loops.cancel_modal_call", cancel):
        await loops._finalize_done(await store.get_job("j_root"))
    assert (await store.get_job("j_root")).status == JobStatus.running  # held open
    assert (await store.get_job("j_c")).status == JobStatus.running     # not reaped
    cancel.assert_not_awaited()


async def test_depth0_done_finalizes_when_children_terminal(fake_redis):
    """Once every child is terminal, the depth-0 job finalizes immediately (no straggler
    to cancel)."""
    await _seed_root_with_child(child_status=JobStatus.done)
    cancel = AsyncMock()
    with patch("runner.loops.cancel_modal_call", cancel):
        await loops._finalize_done(await store.get_job("j_root"))
    assert (await store.get_job("j_root")).status == JobStatus.done
    cancel.assert_not_awaited()


async def test_depth0_done_reaps_straggler_after_grace(fake_redis, monkeypatch):
    """Idea 4: past the barrier grace cap, a still-running child is a wedged orphan —
    finalize the depth-0 job and cancel the straggler (the gap that used to let oneshot
    children run to Modal's 2h cap)."""
    monkeypatch.setattr(loops, "DEPTH0_BARRIER_GRACE_SECONDS", 0)
    await _seed_root_with_child(child_status=JobStatus.running)
    cancel = AsyncMock()
    with patch("runner.loops.cancel_modal_call", cancel):
        await loops._finalize_done(await store.get_job("j_root"))
    assert (await store.get_job("j_root")).status == JobStatus.done
    assert (await store.get_job("j_c")).status == JobStatus.cancelled
    cancel.assert_awaited_once_with("sb_c")


async def test_depth0_done_no_children_finalizes(fake_redis):
    """A depth-0 agent with no children (e.g. planning-only) finalizes with no barrier."""
    await _seed_session()
    await store.create_job(Job(id="j_root", session_id="s_a", depth=0, kind=JobKind.agent,
                               status=JobStatus.running, sandbox_id="exec_1",
                               backend="cloud_run_job"))
    await loops._finalize_done(await store.get_job("j_root"))
    assert (await store.get_job("j_root")).status == JobStatus.done


# ---- reconcile: SEV-12 re-fetch ----------------------------------------

async def test_reconcile_skips_job_that_transitioned(fake_redis):
    """SEV-12: a job in the running index that already moved to done must be skipped
    (poll never called) rather than re-finalized on a stale snapshot."""
    await _seed_session()
    await store.create_job(Job(id="j_1", session_id="s_a", depth=1, status=JobStatus.running,
                               sandbox_id="sb_1", backend="modal"))
    await store.set_job_status("j_1", JobStatus.done)          # actual status -> done
    await store.get_redis().sadd("jobs:by_status:running", "j_1")  # stale index membership
    poll = AsyncMock(return_value="failed")
    with patch("runner.loops.poll_modal_call", poll):
        await loops._reconcile_once()
    poll.assert_not_awaited()
    assert (await store.get_job("j_1")).status == JobStatus.done  # untouched


# ---- SEV-6 terminal-session cleanup (PR2: token revoke; no volume to reclaim) ----

async def test_cleanup_terminal_session_once(fake_redis, monkeypatch):
    monkeypatch.setattr(loops, "CLEANUP_GRACE_SECONDS", 0)  # skip the grace window in test
    await _seed_session()
    await _seed_root(status=JobStatus.done, sandbox_id="exec_1", backend="cloud_run_job")
    tok = await store.mint_agent_token("s_a")
    await loops._cleanup_terminal_sessions()
    await loops._cleanup_terminal_sessions()  # second pass: already cleaned (no error)
    assert await store.resolve_agent_token(tok) is None  # token revoked


async def test_cleanup_respects_grace_window(fake_redis, monkeypatch):
    """First terminal pass only STAMPS; the irreversible cleanup waits out the grace."""
    monkeypatch.setattr(loops, "CLEANUP_GRACE_SECONDS", 9999)
    await _seed_session()
    await _seed_root(status=JobStatus.done, sandbox_id="exec_1", backend="cloud_run_job")
    tok = await store.mint_agent_token("s_a")
    await loops._cleanup_terminal_sessions()
    assert await store.resolve_agent_token(tok) == "s_a"  # within grace -> not revoked yet


async def test_cleanup_skips_session_with_running_job(fake_redis):
    await _seed_session()
    await _seed_root(status=JobStatus.running, sandbox_id="exec_1", backend="cloud_run_job")
    tok = await store.mint_agent_token("s_a")
    await loops._cleanup_terminal_sessions()
    assert await store.resolve_agent_token(tok) == "s_a"  # not terminal -> untouched
