"""Store helpers for the autonomous-loop record (Redis key loop:{sid})."""

from __future__ import annotations

import pytest

from infra import store
from infra.schemas import LoopStatus, RoundRecord

pytestmark = pytest.mark.usefixtures("fake_redis")


async def test_create_and_get_loop():
    await store.create_loop("s1", max_rounds=5, goal_metric=0.9, current_job_id="j_root")
    loop = await store.get_loop("s1")
    assert loop is not None
    assert loop.status == LoopStatus.running
    assert loop.max_rounds == 5
    assert loop.goal_metric == 0.9
    assert loop.current_job_id == "j_root"
    assert loop.rounds == []


async def test_get_missing_loop_is_none():
    assert await store.get_loop("nope") is None


async def test_append_round():
    await store.create_loop("s1", max_rounds=5)
    await store.append_round("s1", RoundRecord(round_index=1, job_id="j_1", best_metric=0.4))
    await store.append_round("s1", RoundRecord(round_index=2, job_id="j_2", best_metric=0.6))
    loop = await store.get_loop("s1")
    assert [r.round_index for r in loop.rounds] == [1, 2]
    assert loop.rounds[-1].best_metric == 0.6


async def test_request_stop():
    await store.create_loop("s1", max_rounds=5)
    await store.request_loop_stop("s1")
    assert (await store.get_loop("s1")).stop_requested is True


async def test_set_status_and_reason():
    await store.create_loop("s1", max_rounds=5)
    await store.set_loop_status("s1", LoopStatus.completed, reason="max_rounds")
    loop = await store.get_loop("s1")
    assert loop.status == LoopStatus.completed
    assert loop.stop_reason == "max_rounds"


async def test_set_current_job():
    await store.create_loop("s1", max_rounds=5, current_job_id="j_1")
    await store.set_loop_current_job("s1", "j_2")
    assert (await store.get_loop("s1")).current_job_id == "j_2"
