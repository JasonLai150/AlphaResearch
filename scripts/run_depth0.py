"""Phase 1 DoD harness: run a depth-0 agent locally against Redis (no UI, no cloud).

    docker compose -f deploy/docker-compose.dev.yml up -d
    cp .env.example .env   # set ANTHROPIC_API_KEY
    uv run python scripts/run_depth0.py "Improve PPO sample efficiency on MiniGrid-DoorKey-8x8"

Then inspect Redis (RedisInsight on :8001) for session/job/run keys + the events Stream.
"""

from __future__ import annotations

import asyncio
import sys

from agent.run_agent import run_agent
from infra import store
from infra.config import settings
from infra.schemas import Job, JobKind


async def main(goal: str) -> None:
    sid = store.new_id("s")
    root_id = store.new_id("j")
    await store.create_session(sid, user_id="local", goal=goal, budget=settings.default_budget)
    await store.create_job(
        Job(id=root_id, session_id=sid, parent_job_id=None, depth=0, kind=JobKind.agent,
            params={"goal": goal})
    )
    print(f"session={sid} root_job={root_id} backend={settings.dispatch_backend}")
    await run_agent(root_id)

    state = await store.read_state(sid)
    print("\n=== final state ===")
    print(f"budget left: {state['budget']}")
    for run in state["runs"]:
        print(f"- {run['job_id']} [{run['status']}] {run['summary']}")


if __name__ == "__main__":
    default_goal = "Improve PPO sample efficiency on MiniGrid-DoorKey-8x8"
    goal = sys.argv[1] if len(sys.argv) > 1 else default_goal
    asyncio.run(main(goal))
