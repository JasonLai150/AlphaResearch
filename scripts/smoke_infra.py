"""Infra smoke test — NO Anthropic key needed. Exercises the store seam + dispatch
+ experiment stub against a real Redis, validating RedisJSON docs, the budget
counter, the children set, the event Stream, and artifact writes.

    docker compose -f deploy/docker-compose.dev.yml up -d
    uv run python scripts/smoke_infra.py
"""

from __future__ import annotations

import asyncio

from infra import dispatch, store
from infra.config import settings
from infra.observability import init_observability
from infra.schemas import Job, JobKind


async def main() -> None:
    sid = store.new_id("s")
    root = store.new_id("j")
    await store.create_session(sid, "local", "smoke goal", settings.default_budget)
    await store.create_job(
        Job(id=root, session_id=sid, depth=0, kind=JobKind.agent, params={"goal": "smoke"})
    )
    parent = dispatch.ParentRef(job_id=root, session_id=sid, depth=0)

    c1 = await dispatch.dispatch(
        parent, kind="experiment", goal="ppo baseline",
        params={"env_id": "MiniGrid-DoorKey-8x8-v0", "trainer": "ppo", "lr": 3e-4},
    )
    c2 = await dispatch.dispatch(
        parent, kind="experiment", goal="higher lr",
        params={"env_id": "MiniGrid-DoorKey-8x8-v0", "trainer": "ppo", "lr": 1e-2},
    )

    state = await store.read_state(sid)
    runs = {r["job_id"]: r for r in state["runs"]}
    children = await store.get_children(root)

    assert state["session"] is not None, "session missing"
    assert c1 in runs and c2 in runs, f"runs missing: {list(runs)}"
    assert len(children) == 2, f"expected 2 children, got {children}"
    # default budget 100, two dispatches at cost 1 each
    assert state["budget"] == settings.default_budget - 2, state["budget"]

    # event stream has entries
    r = store.get_redis()
    n_events = await r.xlen(f"session:{sid}:events")
    assert n_events > 0, "no events on the stream"

    print(f"session={sid}  budget_left={state['budget']}  events={n_events}")
    for run in state["runs"]:
        jid, status = run["job_id"], run["status"]
        reward = run["metrics"].get("final_reward")
        print(f"  - {jid} [{status}] reward={reward} :: {run['summary']}")
    print("SMOKE OK")


if __name__ == "__main__":
    init_observability("smoke-infra")
    asyncio.run(main())
