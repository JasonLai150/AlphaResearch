"""Runner loops: spawn gating (SEV-1), reconcile re-fetch (SEV-12), result
sentinel handling (SEV-7), orphan cancellation (SEV-8), terminal-session
cleanup (SEV-6). Modal + Cloud Run spawns/polls are mocked."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infra import store
from infra.schemas import Job, JobKind, JobStatus
from runner import loops, modal_client

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
    spawn.assert_awaited_once_with("s_a", "j_root")
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

async def test_dispatch_loop_spawns_sub_agent_and_writes_record(fake_redis):
    await _seed_session()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               kind=JobKind.agent, status=JobStatus.queued,
                               params={"plan": {"id": "p"}, "idea_id": "i",
                                       "strategy": "exploration: x"}))
    await store.enqueue_dispatch("j_c")
    spawn = AsyncMock(return_value="sb_c")
    wrec = MagicMock()
    with patch("runner.loops.spawn_sub_agent", spawn), \
         patch("runner.loops.write_dispatch_record", wrec):
        await loops._consume_dispatches_once()
    spawn.assert_awaited_once_with("j_c", "s_a")
    wrec.assert_called_once()  # dispatch record written into the volume before spawn
    j = await store.get_job("j_c")
    assert j.sandbox_id == "sb_c" and j.status == JobStatus.running and j.backend == "modal"


# ---- reconcile: failure + success --------------------------------------

async def test_reconcile_marks_failed_on_dead_sandbox(fake_redis):
    await _seed_session()
    await store.create_job(Job(id="j_1", session_id="s_a", depth=1, status=JobStatus.running,
                               sandbox_id="sb_1", backend="modal"))
    with patch("runner.loops.poll_modal_call", AsyncMock(return_value="failed")), \
         patch("runner.loops.delete_session_volume", AsyncMock()):
        await loops._reconcile_once()
    assert (await store.get_job("j_1")).status == JobStatus.failed
    run = await store.get_run("j_1")
    assert run is not None and run.status == "failed"


async def test_reconcile_done_reads_result_and_uploads(fake_redis):
    await _seed_session()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               status=JobStatus.running, sandbox_id="sb_c", backend="modal"))
    rp, _ = modal_client.results_for("s_a", "j_c")
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"job_id": "j_c", "status": "done", "summary": "ok",
                              "metrics": {"r": 0.5}}))
    modal_client.result_done_sentinel("s_a", "j_c").write_text("done")
    with patch("runner.loops.poll_modal_call", AsyncMock(return_value="done")), \
         patch("runner.loops.reload_volume", AsyncMock()), \
         patch("runner.loops.upload_artifacts", AsyncMock(return_value=[])), \
         patch("runner.loops.delete_session_volume", AsyncMock()):
        await loops._reconcile_once()
    assert (await store.get_job("j_c")).status == JobStatus.done
    run = await store.get_run("j_c")
    assert run.summary == "ok" and run.metrics["r"] == 0.5


async def test_reconcile_done_without_sentinel_fails(fake_redis):
    """SEV-7: completed but no .done sentinel -> failed, not a silent empty done."""
    await _seed_session()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               status=JobStatus.running, sandbox_id="sb_c", backend="modal"))
    rp, _ = modal_client.results_for("s_a", "j_c")
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps({"summary": "ok"}))  # result present, NO sentinel
    with patch("runner.loops.poll_modal_call", AsyncMock(return_value="done")), \
         patch("runner.loops.reload_volume", AsyncMock()), \
         patch("runner.loops.upload_artifacts", AsyncMock(return_value=[])), \
         patch("runner.loops.delete_session_volume", AsyncMock()):
        await loops._reconcile_once()
    assert (await store.get_job("j_c")).status == JobStatus.failed


async def test_reconcile_done_with_invalid_json_fails(fake_redis):
    """SEV-7: sentinel present but JSON torn -> failed."""
    await _seed_session()
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root", depth=1,
                               status=JobStatus.running, sandbox_id="sb_c", backend="modal"))
    rp, _ = modal_client.results_for("s_a", "j_c")
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text("{not valid json")
    modal_client.result_done_sentinel("s_a", "j_c").write_text("done")
    with patch("runner.loops.poll_modal_call", AsyncMock(return_value="done")), \
         patch("runner.loops.reload_volume", AsyncMock()), \
         patch("runner.loops.upload_artifacts", AsyncMock(return_value=[])), \
         patch("runner.loops.delete_session_volume", AsyncMock()):
        await loops._reconcile_once()
    assert (await store.get_job("j_c")).status == JobStatus.failed


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
         patch("runner.loops.cancel_modal_call", cancel), \
         patch("runner.loops.reload_volume", AsyncMock()), \
         patch("runner.loops.upload_artifacts", AsyncMock(return_value=[])), \
         patch("runner.loops.delete_session_volume", AsyncMock()):
        await loops._reconcile_once()
    assert (await store.get_job("j_root")).status == JobStatus.failed
    assert (await store.get_job("j_c")).status == JobStatus.cancelled
    cancel.assert_awaited_once_with("sb_c")


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
    with patch("runner.loops.poll_modal_call", poll), \
         patch("runner.loops.delete_session_volume", AsyncMock()):
        await loops._reconcile_once()
    poll.assert_not_awaited()
    assert (await store.get_job("j_1")).status == JobStatus.done  # untouched


# ---- SEV-6 terminal-session cleanup ------------------------------------

async def test_cleanup_terminal_session_once(fake_redis):
    await _seed_session()
    await _seed_root(status=JobStatus.done, sandbox_id="exec_1", backend="cloud_run_job")
    tok = await store.mint_agent_token("s_a")
    delvol = AsyncMock()
    with patch("runner.loops.delete_session_volume", delvol):
        await loops._cleanup_terminal_sessions()
        await loops._cleanup_terminal_sessions()  # second pass: already cleaned
    delvol.assert_awaited_once_with("s_a")
    assert await store.resolve_agent_token(tok) is None  # token revoked


async def test_cleanup_skips_session_with_running_job(fake_redis):
    await _seed_session()
    await _seed_root(status=JobStatus.running, sandbox_id="exec_1", backend="cloud_run_job")
    delvol = AsyncMock()
    with patch("runner.loops.delete_session_volume", delvol):
        await loops._cleanup_terminal_sessions()
    delvol.assert_not_awaited()
