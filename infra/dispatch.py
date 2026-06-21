"""Generic dispatch(kind, payload) — plan §2.5 deliverable #2 + #4.

One primitive launches either an agentic sub-agent or a non-agentic experiment.
The DISPATCH_BACKEND switch selects in-process execution (local, no cloud) or
Modal spawn. Guardrails (depth, fanout, budget) are enforced here — the single
choke point that the future compute-allocator grows from.
"""

from __future__ import annotations

from dataclasses import dataclass

from infra import store
from infra.config import settings
from infra.schemas import EventEnvelope, EventType, Job, JobKind


class DispatchError(Exception):
    pass


class BudgetExceeded(DispatchError):
    pass


class DepthExceeded(DispatchError):
    pass


class FanoutExceeded(DispatchError):
    pass


@dataclass
class ParentRef:
    job_id: str
    session_id: str
    depth: int


async def dispatch(
    parent: ParentRef,
    kind: str,
    goal: str = "",
    strategy: str = "",
    params: dict | None = None,
    gpu: bool = False,
    cost: int | None = None,
) -> str:
    """Create + launch a child job under `parent`. Returns the child job id.

    Raises DepthExceeded / FanoutExceeded / BudgetExceeded so the calling tool
    can tell the agent to wrap up instead of spawning more work.
    """
    params = dict(params or {})
    kind_enum = JobKind(kind)
    cost = settings.dispatch_cost if cost is None else cost
    child_depth = parent.depth + 1

    # Guardrails (= compute-allocation v0)
    if kind_enum is JobKind.agent and child_depth > settings.max_depth:
        raise DepthExceeded(f"max_depth={settings.max_depth} reached")
    # Atomic fanout claim — avoids the check-then-act TOCTOU race when the model
    # issues several dispatch_job tool calls concurrently (each in its own task).
    if not await store.claim_fanout(parent.job_id, settings.max_fanout):
        raise FanoutExceeded(f"max_fanout={settings.max_fanout} reached")

    try:
        remaining = await store.decr_budget(parent.session_id, cost)
        if remaining < 0:
            await store.incr_budget(parent.session_id, cost)  # refund the failed claim
            raise BudgetExceeded("session budget exhausted")

        child_id = store.new_id("j")
        child = Job(
            id=child_id,
            session_id=parent.session_id,
            parent_job_id=parent.job_id,
            depth=child_depth,
            kind=kind_enum,
            params={**params, "goal": goal, "strategy": strategy},
            gpu=gpu,
        )
        await store.create_job(child)
        await store.emit_event(
            EventEnvelope(
                session_id=parent.session_id,
                job_id=child_id,
                parent_job_id=parent.job_id,
                depth=child_depth,
                type=EventType.spawn,
                payload={
                    "kind": kind,
                    "goal": goal,
                    "strategy": strategy,
                    "budget_left": remaining,
                },
            )
        )

        await _launch(child)
        return child_id
    except Exception:
        await store.release_fanout(parent.job_id)  # refund the slot on any failure
        raise


async def _launch(job: Job) -> None:
    # Agent jobs are Claude Code harness containers owned by the RUNNER (separate
    # component): dispatch only creates the job + spawn event and leaves it `pending`
    # for the runner to claim. The in-process SDK run_agent path was removed.
    # Only experiment (non-agentic compute) jobs execute here.
    if job.kind is not JobKind.experiment:
        return

    backend = settings.dispatch_backend
    if backend == "local":
        # In-process so the whole tree runs against a local Redis with no cloud.
        # Children run to completion before dispatch returns (deterministic for P0);
        # real parallelism is the modal path.
        from infra.registry.experiment import run_experiment_stub

        await run_experiment_stub(job)
    elif backend == "modal":
        from infra.modal_app import spawn_job

        # Set status BEFORE the remote can start; afterwards write only the call id,
        # so a fast remote job that already reached `done` is never demoted to `running`.
        await store.set_job_status(job.id, "running")
        call_id = await spawn_job(job.id)
        await store.update_job(job.id, sandbox_id=call_id, backend="modal")
    else:
        raise DispatchError(f"unknown DISPATCH_BACKEND={backend!r}")
