"""Claude Agent SDK tools — thin wrappers over the infra seam (plan §2.5).

Tools resolve the current job/session from a ContextVar set by run_agent, so the
model never passes ids around and one job cannot act on another.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass

from claude_agent_sdk import create_sdk_mcp_server, tool

from infra import dispatch, store
from infra.schemas import EventEnvelope, EventType, JobStatus, RunResult


@dataclass
class AgentContext:
    job_id: str
    session_id: str
    parent_job_id: str | None
    depth: int


AGENT_CTX: ContextVar[AgentContext] = ContextVar("agent_ctx")


def _ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


@tool(
    "dispatch_job",
    "Spawn a child job. kind='experiment' runs a prebaked trainer (params: env_id, "
    "trainer, lr, total_steps). kind='agent' spawns a sub-researcher. Returns child id.",
    {"kind": str, "goal": str, "strategy": str, "params": dict},
)
async def dispatch_job(args: dict) -> dict:
    ctx = AGENT_CTX.get()
    parent = dispatch.ParentRef(job_id=ctx.job_id, session_id=ctx.session_id, depth=ctx.depth)
    try:
        child_id = await dispatch.dispatch(
            parent,
            kind=args.get("kind", "experiment"),
            goal=args.get("goal", ""),
            strategy=args.get("strategy", ""),
            params=args.get("params", {}) or {},
        )
    except dispatch.BudgetExceeded:
        return _ok("Budget exhausted — do not dispatch more. Review results and finalize.")
    except dispatch.DepthExceeded:
        return _ok(
            "Max recursion depth reached — run experiments directly "
            "(kind='experiment'), then finalize."
        )
    except dispatch.FanoutExceeded:
        return _ok(
            "Max fanout reached — review the children you already have with "
            "query_children, then finalize."
        )
    return _ok(f"Dispatched {args.get('kind', 'experiment')} job {child_id}.")


@tool(
    "report_progress",
    "Post a short status update or metrics to the user's live stream.",
    {"status": str, "note": str, "metrics": dict},
)
async def report_progress(args: dict) -> dict:
    ctx = AGENT_CTX.get()
    metrics = args.get("metrics") or {}
    etype = EventType.metric if metrics else EventType.log
    payload = {"status": args.get("status"), "note": args.get("note"), "metrics": metrics}
    # Lift known scalar metrics to the top level so the UI's flat metric contract
    # (payload.reward / payload.step) sees agent-reported metrics, like the experiment stub.
    if isinstance(metrics.get("step"), (int, float)):
        payload["step"] = metrics["step"]
    if isinstance(metrics.get("reward"), (int, float)):
        payload["reward"] = metrics["reward"]
    await store.emit_event(
        EventEnvelope(
            session_id=ctx.session_id,
            job_id=ctx.job_id,
            parent_job_id=ctx.parent_job_id,
            depth=ctx.depth,
            type=etype,
            payload=payload,
        )
    )
    return _ok("ok")


@tool("query_children", "Read finalized summaries + metrics of jobs you spawned.", {})
async def query_children(args: dict) -> dict:
    ctx = AGENT_CTX.get()
    runs = await store.get_children_runs(ctx.job_id)
    if not runs:
        return _ok("No children have finished yet.")
    lines = [
        f"- {r.job_id} [{r.status}] {r.summary} metrics={r.metrics}" for r in runs
    ]
    return _ok("Children results:\n" + "\n".join(lines))


@tool(
    "finalize",
    "Write this job's FINAL summary + metrics. Flows up to your parent / the user. "
    "Call exactly once when done.",
    {"summary": str, "metrics": dict},
)
async def finalize(args: dict) -> dict:
    ctx = AGENT_CTX.get()
    run = RunResult(
        job_id=ctx.job_id,
        status="done",
        summary=args.get("summary", ""),
        metrics=args.get("metrics", {}) or {},
    )
    await store.write_run(run)
    await store.set_job_status(ctx.job_id, JobStatus.done)
    await store.emit_event(
        EventEnvelope(
            session_id=ctx.session_id,
            job_id=ctx.job_id,
            parent_job_id=ctx.parent_job_id,
            depth=ctx.depth,
            type=EventType.summary,
            payload={"summary": run.summary, "metrics": run.metrics},
        )
    )
    return _ok("Finalized.")


def build_mcp_server():
    return create_sdk_mcp_server(
        name="alpha",
        version="1.0.0",
        tools=[dispatch_job, report_progress, query_children, finalize],
    )


def allowed_tool_names() -> list[str]:
    return [
        "mcp__alpha__dispatch_job",
        "mcp__alpha__report_progress",
        "mcp__alpha__query_children",
        "mcp__alpha__finalize",
    ]
