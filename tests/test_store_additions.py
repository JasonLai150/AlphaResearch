"""Data-layer additions for the backend MVP (Task 1) + the SEV fixes that live
in the store: status-index integrity (SEV-3), per-session tokens (SEV-4),
deterministic artifact ids (SEV-10), and the runner leader lease (SEV-2)."""

from __future__ import annotations

import pytest

from infra import store
from infra.schemas import ArtifactRef, Job, JobKind, JobStatus, Message, RunResult

pytestmark = pytest.mark.asyncio


async def test_message_roundtrip(fake_redis):
    m = Message(session_id="s_a", job_id="j_1", role="user", content="hi")
    eid = await store.append_message(m)
    assert eid
    got = await store.read_transcript("s_a")
    assert len(got) == 1
    assert got[0].content == "hi"
    assert got[0].role == "user"


async def test_dispatch_queue_fifo(fake_redis):
    e1 = await store.enqueue_dispatch("j_1")
    e2 = await store.enqueue_dispatch("j_2")
    entries = await store.read_stream(store.DISPATCH_QUEUE, last_id="0", count=10, block_ms=0)
    assert [f["job_id"] for _, f in entries] == ["j_1", "j_2"]
    assert entries[0][0] == e1 and entries[1][0] == e2


async def test_link_child_and_statuses(fake_redis):
    parent = Job(id="j_p", session_id="s_a", depth=0, kind=JobKind.agent, status=JobStatus.running)
    child = Job(id="j_c", session_id="s_a", parent_job_id="j_p", depth=1,
                kind=JobKind.agent, status=JobStatus.running)
    await store.create_job(parent)
    await store.create_job(child)
    await store.link_child("j_p", "j_c", "s_a")
    statuses = await store.child_statuses("j_p")
    assert len(statuses) == 1 and statuses[0]["job_id"] == "j_c"
    assert statuses[0]["done"] is False

    await store.write_run(RunResult(job_id="j_c", status="done", summary="ok",
                                    metrics={"score": 0.9}))
    statuses = await store.child_statuses("j_p")
    assert statuses[0]["done"] is True
    assert statuses[0]["summary"] == "ok"
    assert statuses[0]["metrics"]["score"] == 0.9


async def test_list_jobs_by_status_tracks_transitions(fake_redis):
    j1 = Job(id="j_1", session_id="s_a", status=JobStatus.running)
    j2 = Job(id="j_2", session_id="s_a", status=JobStatus.done)
    j3 = Job(id="j_3", session_id="s_a", status=JobStatus.running)
    for j in (j1, j2, j3):
        await store.create_job(j)
    running = await store.list_jobs_by_status(JobStatus.running)
    assert {j.id for j in running} == {"j_1", "j_3"}

    # A transition must move the job between index sets (SEV-3).
    await store.set_job_status("j_1", JobStatus.done)
    running = await store.list_jobs_by_status(JobStatus.running)
    assert {j.id for j in running} == {"j_3"}
    done = await store.list_jobs_by_status(JobStatus.done)
    assert {j.id for j in done} == {"j_1", "j_2"}


async def test_set_status_is_field_level_no_clobber(fake_redis):
    """SEV-3: setting status must not wipe a concurrently-written sandbox_id."""
    j = Job(id="j_1", session_id="s_a", status=JobStatus.queued)
    await store.create_job(j)
    await store.update_job("j_1", sandbox_id="sb_xyz", backend="cloud_run_job")
    await store.set_job_status("j_1", JobStatus.running)
    got = await store.get_job("j_1")
    assert got.status == JobStatus.running
    assert got.sandbox_id == "sb_xyz"  # not clobbered
    assert got.backend == "cloud_run_job"


async def test_artifact_link_and_list(fake_redis):
    ref = await store.put_artifact("s_a", "j_1", "plot", b"PNGBYTES", "curve.png", "loss curve")
    listed = await store.list_artifacts_for("j_1")
    assert len(listed) == 1
    assert listed[0].id == ref.id and listed[0].kind == "plot"


async def test_deterministic_artifact_id_is_stable(fake_redis):
    a1 = store.deterministic_artifact_id("s_a", "j_1", "loss.png")
    a2 = store.deterministic_artifact_id("s_a", "j_1", "loss.png")
    a3 = store.deterministic_artifact_id("s_a", "j_1", "other.png")
    assert a1 == a2 and a1.startswith("a_")
    assert a1 != a3


async def test_artifact_ref_idempotent_relink(fake_redis):
    """SEV-10: re-storing the same ref id must not create a duplicate."""
    aid = store.deterministic_artifact_id("s_a", "j_1", "loss.png")
    ref = ArtifactRef(id=aid, job_id="j_1", kind="plot", url="gs://b/x", bytes=3)
    r = store.get_redis()
    for _ in range(3):  # simulate reconcile retries
        await r.json().set(f"artifact:{aid}", "$", ref.model_dump())
        await store.link_artifact_to_job("j_1", aid)
    listed = await store.list_artifacts_for("j_1")
    assert len(listed) == 1


async def test_read_full_session(fake_redis):
    await store.create_session("s_a", "u_1", "explore RL", 100)
    parent = Job(id="j_p", session_id="s_a", depth=0, kind=JobKind.agent, status=JobStatus.done)
    child = Job(id="j_c", session_id="s_a", parent_job_id="j_p", depth=1,
                kind=JobKind.agent, status=JobStatus.done)
    await store.create_job(parent)
    await store.create_job(child)
    await store.link_child("j_p", "j_c", "s_a")
    await store.write_run(RunResult(job_id="j_c", summary="done", metrics={"r": 0.5}))
    await store.append_message(Message(session_id="s_a", job_id="j_p", role="user",
                                       content="explore"))
    full = await store.read_full_session("s_a")
    assert full["session"]["id"] == "s_a"
    assert {j["id"] for j in full["jobs"]} == {"j_p", "j_c"}
    assert len(full["runs"]) == 1 and full["runs"][0]["job_id"] == "j_c"
    assert len(full["transcript"]) == 1
    assert full["tree"]["j_p"] == ["j_c"]


# ---- SEV-4: per-session ephemeral agent tokens -------------------------

async def test_agent_token_mint_resolve(fake_redis):
    tok = await store.mint_agent_token("s_a")
    assert tok and await store.resolve_agent_token(tok) == "s_a"
    assert await store.resolve_agent_token("bogus") is None
    assert await store.resolve_agent_token(None) is None


async def test_get_session_token_is_idempotent(fake_redis):
    t1 = await store.get_session_token("s_a")
    t2 = await store.get_session_token("s_a")  # sub-agent spawn reuses main's token
    assert t1 == t2


async def test_revoke_session_token(fake_redis):
    tok = await store.mint_agent_token("s_a")
    await store.revoke_session_token("s_a")
    assert await store.resolve_agent_token(tok) is None


# ---- SEV-2: runner leader lease ----------------------------------------

async def test_leader_lease_single_winner(fake_redis):
    assert await store.acquire_leader_lease("runner_1") is True
    assert await store.acquire_leader_lease("runner_2") is False  # someone holds it
    assert await store.acquire_leader_lease("runner_1") is True  # owner re-acquires


async def test_leader_lease_refresh_only_owner(fake_redis):
    await store.acquire_leader_lease("runner_1")
    assert await store.refresh_leader_lease("runner_1") is True
    assert await store.refresh_leader_lease("runner_2") is False  # not the owner


async def test_leader_lease_release(fake_redis):
    await store.acquire_leader_lease("runner_1")
    await store.release_leader_lease("runner_1")
    assert await store.acquire_leader_lease("runner_2") is True  # free after release
