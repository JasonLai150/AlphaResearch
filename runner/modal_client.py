"""Modal-side helpers for the sub-agent path: per-session volume naming, local
mount paths, dispatch-record I/O, and the spawn/poll/cancel lifecycle.

Volume layout per session. The same volume is mounted inside the sub-agent
container at ``/workspace/.dispatched`` and visible to the runner host at
``$ALPHA_VOLUME_ROOT/<sid>/.dispatched`` — i.e. ``dispatch_dir(sid)``:

    .dispatched/
        <jid>.json                — dispatch record (runner writes; sub-agent reads)
        <jid>.result.json         — sub-agent's RunResult (atomic write, SEV-7)
        <jid>.result.json.done    — sentinel: result fully written (SEV-7)
        <jid>.failed.json         — runner writes on sandbox death / timeout
        artifacts/<jid>/*         — sub-agent's binary outputs; runner ships to GCS

The main-agent path uses Cloud Run Jobs (runner/cloud_run_client.py), NOT this
module — main-agent has no shared filesystem with the runner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from infra import store
from infra.config import settings

# ---- naming + paths ----------------------------------------------------

def session_volume_name(sid: str) -> str:
    return f"alpha-session-{sid}"


def local_volume_path(sid: str) -> Path:
    return Path(settings.volume_root) / sid


def dispatch_dir(sid: str) -> Path:
    return local_volume_path(sid) / ".dispatched"


def results_for(sid: str, jid: str) -> tuple[Path, Path]:
    d = dispatch_dir(sid)
    return d / f"{jid}.result.json", d / f"{jid}.failed.json"


def result_done_sentinel(sid: str, jid: str) -> Path:
    """SEV-7: reconcile must see this before reading <jid>.result.json."""
    return dispatch_dir(sid) / f"{jid}.result.json.done"


def artifacts_dir(sid: str, jid: str) -> Path:
    return dispatch_dir(sid) / "artifacts" / jid


def write_dispatch_record(sid: str, jid: str, record: dict) -> Path:
    """Place the dispatch record into the session volume so the sub-agent reads its
    plan/idea on boot. Called by the dispatch loop before the Modal spawn."""
    d = dispatch_dir(sid)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{jid}.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True))
    return path


# ---- Modal lifecycle (sub-agent) ---------------------------------------
#
# Imports of the modal SDK are lazy so unit tests (which patch these functions)
# never import or touch Modal. The runner mounts the per-session volume at
# /workspace/.dispatched and commits the runner-side writes before spawning.

def _modal():
    import modal  # lazy
    return modal


async def _session_volume(sid: str):
    modal = _modal()
    return modal.Volume.from_name(session_volume_name(sid), create_if_missing=True)


async def spawn_sub_agent(job_id: str, session_id: str) -> str:
    """Spawn the sub_agent Modal Function for one dispatched idea. Returns the
    FunctionCall object_id (stored as Job.sandbox_id). Injects the per-session
    token + runner URL (SEV-4) so the sub-agent's hooks authenticate as this
    session only."""
    modal = _modal()
    token = await store.get_session_token(session_id)
    vol = await _session_volume(session_id)
    try:
        await vol.commit.aio()  # flush runner-written dispatch record before spawn
    except Exception:
        pass
    fn = modal.Function.from_name(settings.modal_app_name, "sub_agent")
    call = await fn.with_options(volumes={"/workspace/.dispatched": vol}).spawn.aio(
        job_id=job_id, session_id=session_id,
        internal_token=token, internal_runner_url=settings.internal_runner_url,
    )
    return call.object_id


async def poll_modal_call(sandbox_id: str) -> Literal["running", "done", "failed"]:
    """Map a Modal FunctionCall to our tri-state. Uses the async ``.aio`` variant so
    it never blocks the runner's event loop.

    Semantics of ``fc.get(timeout=0)``: returns => the function finished OK; raises
    TimeoutError => still executing; raises the function's exception => it terminated
    with a failure. We therefore treat ANY non-timeout, non-transient exception as
    ``failed`` (so a crashed sub-agent is finalized, not polled forever) and keep
    ``running`` only for clearly-transient connectivity errors.
    """
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


async def reload_volume(sid: str) -> None:
    """Force a Modal volume reload so the runner sees the sub-agent's writes.
    No-op in tests/local mode (the volume is just a tmp dir)."""
    try:
        vol = await _session_volume(sid)
        await vol.reload.aio()
    except Exception:
        pass


async def delete_session_volume(sid: str) -> None:
    """Reclaim a per-session volume once the whole session is terminal (SEV-6:
    avoid the unbounded Modal Volume leak / quota cap). Offloaded to a thread —
    Volume.delete() is blocking and must not stall the runner's event loop."""
    import asyncio
    try:
        modal = _modal()
        vol = modal.Volume.from_name(session_volume_name(sid))
        await asyncio.to_thread(vol.delete)
    except Exception:
        pass
