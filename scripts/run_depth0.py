"""Start a research session locally (no UI): create the session + root job and
enqueue it on `sessions:queue` for the runner to pick up.

    docker compose -f deploy/docker-compose.dev.yml up -d
    cp .env.example .env
    uv run python scripts/run_depth0.py "Improve PPO sample efficiency on MiniGrid-DoorKey-8x8"

The runner (separate component) consumes the queue and launches the depth-0
main-agent harness. Inspect Redis (RedisInsight on :8001) for the keys/streams.
"""

from __future__ import annotations

import asyncio
import sys

from infra import store
from infra.config import settings
from infra.observability import init_observability
from infra.schemas import Job, JobKind


async def main(goal: str) -> None:
    sid = store.new_id("s")
    root_id = store.new_id("j")
    await store.create_session(sid, user_id="local", goal=goal, budget=settings.default_budget)
    await store.create_job(
        Job(id=root_id, session_id=sid, parent_job_id=None, depth=0, kind=JobKind.agent,
            params={"goal": goal})
    )
    await store.enqueue_session(sid)
    print(f"enqueued session={sid} root_job={root_id} backend={settings.dispatch_backend}")
    print("waiting on the runner to launch the depth-0 harness; tail the session events stream.")


if __name__ == "__main__":
    init_observability("dev-depth0")
    default_goal = "Improve PPO sample efficiency on MiniGrid-DoorKey-8x8"
    goal = sys.argv[1] if len(sys.argv) > 1 else default_goal
    asyncio.run(main(goal))
