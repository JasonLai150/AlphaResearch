"""Boot the runner's asyncio background tasks from FastAPI startup.

One leadership task (SEV-2) elects a single active runner via a Redis lease; the
three work loops only act while this instance holds the lease, so a rolling
deploy never double-spawns.
"""

from __future__ import annotations

import asyncio
import secrets

from runner import loops


def start_runner_tasks() -> list[asyncio.Task]:
    runner_id = secrets.token_hex(8)
    return [
        asyncio.create_task(loops.leadership_loop(runner_id)),
        asyncio.create_task(loops.session_loop()),
        asyncio.create_task(loops.dispatch_loop()),
        asyncio.create_task(loops.reconcile_loop()),
    ]
