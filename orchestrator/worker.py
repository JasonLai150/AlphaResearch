"""Decoupled depth-0 worker (prod path): consume `sessions:queue` and run the
root agent. The API's in-process background task (api.py) is the local shortcut;
this is the horizontally-scalable alternative.
"""

from __future__ import annotations

import asyncio

from agent.run_agent import run_agent
from infra import store

GROUP = "workers"


async def run_worker() -> None:
    r = store.get_redis()
    try:
        await r.xgroup_create(store.SESSIONS_QUEUE, GROUP, id="0", mkstream=True)
    except Exception:
        pass  # group already exists
    consumer = store.new_id("worker")
    while True:
        resp = await r.xreadgroup(GROUP, consumer, {store.SESSIONS_QUEUE: ">"}, count=1, block=5000)
        if not resp:
            continue
        for _stream, entries in resp:
            for msg_id, fields in entries:
                sid = fields.get("session_id")
                root = await store.get_root_job(sid) if sid else None
                if root:
                    await run_agent(root)
                await r.xack(store.SESSIONS_QUEUE, GROUP, msg_id)


if __name__ == "__main__":
    asyncio.run(run_worker())
