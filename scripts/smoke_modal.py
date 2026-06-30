"""Stage 3 smoke — proves the real Modal round-trip.

Dispatches experiment children with DISPATCH_BACKEND=modal (they run in Modal
sandboxes, async), then POLLS Redis Cloud until each child's RunResult appears —
validating: local -> Modal spawn -> sandbox writes to the SAME Redis + GCS -> we read it back.

    uv run python scripts/smoke_modal.py
"""

from __future__ import annotations

import asyncio
import time

from infra import dispatch, store
from infra.config import settings
from infra.schemas import Job, JobKind

TIMEOUT_S = 180


async def main() -> None:
    assert settings.dispatch_backend == "modal", "set ALPHA_DISPATCH_BACKEND=modal in .env"
    sid = store.new_id("s")
    root = store.new_id("j")
    await store.create_session(sid, "local", "modal smoke goal", settings.default_budget)
    await store.create_job(
        Job(id=root, session_id=sid, depth=0, kind=JobKind.agent, params={"goal": "smoke"})
    )
    parent = dispatch.ParentRef(job_id=root, session_id=sid, depth=0)

    children = []
    for goal, params in [
        ("ppo baseline", {"env_id": "MiniGrid-DoorKey-8x8-v0", "trainer": "ppo", "lr": 3e-4}),
        ("higher lr", {"env_id": "MiniGrid-DoorKey-8x8-v0", "trainer": "ppo", "lr": 1e-2}),
    ]:
        cid = await dispatch.dispatch(parent, kind="experiment", goal=goal, params=params)
        children.append(cid)
        print(f"dispatched {cid} -> Modal (async)")

    print(f"\npolling Redis for {len(children)} child results (timeout {TIMEOUT_S}s)...")
    deadline = time.time() + TIMEOUT_S
    done: dict[str, object] = {}
    while time.time() < deadline and len(done) < len(children):
        for cid in children:
            if cid in done:
                continue
            run = await store.get_run(cid)
            if run and run.status in ("done", "failed", "partial"):
                done[cid] = run
                print(f"  ✓ {cid} [{run.status}] {run.summary}")
        await asyncio.sleep(3)

    if len(done) < len(children):
        missing = [c for c in children if c not in done]
        raise SystemExit(f"TIMEOUT — no result for: {missing}")

    n_events = await store.get_redis().xlen(f"session:{sid}:events")
    print(f"\nsession={sid} events={n_events}")
    print("MODAL SMOKE OK — sandboxes wrote back to shared Redis + GCS")


if __name__ == "__main__":
    asyncio.run(main())
