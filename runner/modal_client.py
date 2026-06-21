"""Modal-side helpers for the sub-agent path: spawn / poll / cancel.

PR2: there is NO shared filesystem between the runner and sub-agents. The dispatch
record rides as a Modal call argument (the sub_agent function writes it into its own
/workspace/.dispatched on boot), and results + artifacts come back over the runner's
internal HTTP API (POST /internal/result) — never via a Modal Volume. This keeps the
sub-agent boundary identical to the main-agent's (pure HTTP), removing the Cloud-Run-
can't-mount-a-Modal-Volume gap.

The main-agent path uses Cloud Run Jobs (runner/cloud_run_client.py), not this module.
"""

from __future__ import annotations

import json
from typing import Literal

from infra import store
from infra.config import settings

# ---- Modal lifecycle (sub-agent) ---------------------------------------
#
# Imports of the modal SDK are lazy so unit tests (which patch these functions) never
# import or touch Modal.

def _modal():
    import modal  # lazy
    return modal


async def spawn_sub_agent(job_id: str, session_id: str, record: dict) -> str:
    """Spawn the sub_agent Modal Function for one dispatched idea. Returns the
    FunctionCall object_id (stored as Job.sandbox_id). Injects the per-session token +
    runner URL (SEV-4) so the sub-agent's hooks authenticate as this session only, and
    passes the dispatch record so the sub-agent gets its plan/idea without a volume."""
    modal = _modal()
    token = await store.get_session_token(session_id)
    fn = modal.Function.from_name(settings.modal_app_name, "sub_agent")
    call = await fn.spawn.aio(
        job_id=job_id,
        session_id=session_id,
        internal_token=token,
        internal_runner_url=settings.internal_runner_url,
        dispatch_record=json.dumps(record),
        # wandb + Browserbase identifiers so the sub-agent can deterministically
        # screenshot its OWN wandb run (secrets ride in the Modal alpha-secrets).
        wandb_entity=settings.wandb_entity,
        browserbase_context_id=settings.browserbase_context_id,
        browserbase_project_id=settings.browserbase_project_id,
    )
    return call.object_id


async def poll_modal_call(sandbox_id: str) -> Literal["running", "done", "failed"]:
    """Map a Modal FunctionCall to our tri-state. Uses the async ``.aio`` variant so it
    never blocks the runner's event loop.

    ``fc.get(timeout=0)``: returns => finished OK; raises TimeoutError => still running;
    raises the function's exception => terminated with a failure. Any non-timeout,
    non-transient exception is treated as ``failed`` (so a crashed sub-agent is finalized,
    not polled forever); clearly-transient connectivity errors stay ``running``."""
    modal = _modal()
    fc = modal.FunctionCall.from_id(sandbox_id)
    try:
        await fc.get.aio(timeout=0)
        return "done"
    except TimeoutError:
        return "running"
    except Exception as e:  # noqa: BLE001
        name = type(e).__name__.lower()
        if any(t in name for t in ("connection", "timeout", "unavailable", "deadline")):
            return "running"  # transient — keep polling
        return "failed"      # the call terminated with an error


async def cancel_modal_call(sandbox_id: str) -> None:
    """Best-effort cancel (SEV-8: orphan children when a parent dies)."""
    try:
        modal = _modal()
        await modal.FunctionCall.from_id(sandbox_id).cancel.aio()
    except Exception:
        pass
