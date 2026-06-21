"""Runner: reconcile Modal call handles into job status + a status event, so the
UI sees terminal states even if a sandbox dies mid-run (plan §7, Phase 3).

No-op for DISPATCH_BACKEND=local (children finish in-process). Implemented against
the Modal backend in Phase 2/3 — poll `modal.FunctionCall` handles recorded in
`job.modal_call_id` and write `done`/`failed` + emit a status event.
"""

from __future__ import annotations

import asyncio

from infra.config import settings


async def run_runner() -> None:
    if settings.dispatch_backend != "modal":
        return
    # TODO(phase-2/3): poll modal.FunctionCall.from_id(job.modal_call_id) for each
    # running job, reconcile terminal state into store.set_job_status + status event.
    while True:
        await asyncio.sleep(5)
