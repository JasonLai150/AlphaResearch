"""Runner reconcile integration for autonomous loops (runner.loops._advance_loop).

A round's depth-0 agent finishing must either spawn the next round (re-pointing the
session root + enqueueing) or mark the loop terminal — never silently strand it.
"""

from __future__ import annotations

import pytest

from infra import store
from infra.schemas import Job, JobKind, JobStatus, LoopStatus, RoundRecord
from runner import loops

pytestmark = pytest.mark.usefixtures("fake_redis")


async def _autonomous(sid="s_auto", *, max_rounds=5, budget=100, goal_metric=None, rounds=()):
    await store.create_session(sid, "u", "goal", budget, mode="autonomous")
    await store.create_loop(sid, max_rounds=max_rounds, goal_metric=goal_metric,
                            current_job_id="j_1")
    for rr in rounds:
        await store.append_round(sid, rr)
    return sid


def _done_round_job(sid: str, jid: str) -> Job:
    return Job(id=jid, session_id=sid, depth=0, kind=JobKind.agent,
               status=JobStatus.done, backend="cloud_run_job")


async def test_continue_spawns_and_repoints_next_round():
    sid = await _autonomous(rounds=[RoundRecord(round_index=1, job_id="j_1", best_metric=0.3)])
    await loops._advance_loop(_done_round_job(sid, "j_1"))

    loop = await store.get_loop(sid)
    assert loop.status == LoopStatus.running
    assert loop.current_job_id != "j_1"
    new_job = await store.get_job(loop.current_job_id)
    assert new_job.depth == 0 and new_job.status == JobStatus.queued
    # session root re-pointed to the new round so session_loop spawns IT
    doc = await store.get_redis().json().get(store._session_key(sid))
    assert doc["root_job_id"] == loop.current_job_id
    # and the session is re-enqueued
    entries = await store.read_stream(store.SESSIONS_QUEUE, "0", 50, 0)
    assert any(f.get("session_id") == sid for _, f in entries)


async def test_stops_at_max_rounds():
    rounds = [RoundRecord(round_index=i, job_id=f"j_{i}", best_metric=0.1 * i) for i in range(1, 6)]
    sid = await _autonomous(max_rounds=5, rounds=rounds)
    await loops._advance_loop(_done_round_job(sid, "j_5"))  # already-counted round
    loop = await store.get_loop(sid)
    assert loop.status == LoopStatus.completed
    assert "max_rounds" in loop.stop_reason


async def test_backstop_counts_an_unreported_round():
    # Agent crashed before POSTing its round -> the runner still counts it, so
    # max_rounds remains a real backstop.
    sid = await _autonomous(max_rounds=5, rounds=())
    await loops._advance_loop(_done_round_job(sid, "j_crash"))
    loop = await store.get_loop(sid)
    assert len(loop.rounds) == 1
    assert loop.rounds[0].job_id == "j_crash"
    assert loop.rounds[0].best_metric is None
    assert loop.status == LoopStatus.running  # still under max -> spawned next round


async def test_noop_for_non_autonomous_session():
    await store.create_session("s_one", "u", "goal", 100)  # mode defaults to oneshot
    await loops._advance_loop(_done_round_job("s_one", "j_1"))
    assert await store.get_loop("s_one") is None


async def test_stops_on_user_request():
    sid = await _autonomous(rounds=[RoundRecord(round_index=1, job_id="j_1", best_metric=0.3)])
    await store.request_loop_stop(sid)
    await loops._advance_loop(_done_round_job(sid, "j_1"))
    assert (await store.get_loop(sid)).status == LoopStatus.stopped


async def test_failed_round_still_advances_the_loop():
    # A depth-0 round that FAILED (OOM/timeout) must not strand the loop in `running`.
    sid = await _autonomous(max_rounds=5, rounds=())
    job = _done_round_job(sid, "j_fail")
    job.status = JobStatus.failed
    await loops._finalize_failed(job, reason="sandbox died")
    loop = await store.get_loop(sid)
    assert len(loop.rounds) == 1                 # the failed round was counted
    assert loop.status == LoopStatus.running     # under max -> spawned the next round
    assert loop.current_job_id != "j_fail"


async def test_failed_round_at_max_rounds_terminates():
    rounds = [RoundRecord(round_index=i, job_id=f"j_{i}") for i in range(1, 5)]  # 4 done
    sid = await _autonomous(max_rounds=5, rounds=rounds)
    job = _done_round_job(sid, "j_fail")
    job.status = JobStatus.failed
    await loops._finalize_failed(job, reason="sandbox died")  # 5th round -> hits max
    assert (await store.get_loop(sid)).status == LoopStatus.completed
