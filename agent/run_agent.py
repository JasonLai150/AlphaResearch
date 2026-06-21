"""The self-similar agent runtime (plan §2). One program at every depth.

run_agent(job_id) loads the job, runs a Claude Agent SDK loop with the four tools,
streams its text to the session event bus as `log` events, and guarantees a final
RunResult is written even if the model forgets to call finalize.
"""

from __future__ import annotations

import os

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    TextBlock,
    query,
)

from agent.prompts import render_goal_prompt, system_prompt_for
from agent.tools import (
    AGENT_CTX,
    AgentContext,
    allowed_tool_names,
    build_mcp_server,
)
from infra import store
from infra.config import settings
from infra.schemas import EventEnvelope, EventType, JobStatus, RunResult


async def run_agent(job_id: str) -> None:
    # Bridge the key from .env (settings) into the process env for the SDK subprocess.
    if settings.anthropic_api_key:
        os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)

    job = await store.get_job(job_id)
    if job is None:
        raise ValueError(f"unknown job {job_id}")

    ctx = AgentContext(
        job_id=job.id,
        session_id=job.session_id,
        parent_job_id=job.parent_job_id,
        depth=job.depth,
    )
    ctx_token = AGENT_CTX.set(ctx)
    try:
        await store.set_job_status(job.id, JobStatus.running)
        await store.emit_event(
            EventEnvelope(
                session_id=job.session_id,
                job_id=job.id,
                parent_job_id=job.parent_job_id,
                depth=job.depth,
                type=EventType.status,
                payload={"status": "running"},
            )
        )

        options = ClaudeAgentOptions(
            system_prompt=system_prompt_for(job),
            mcp_servers={"alpha": build_mcp_server()},
            allowed_tools=allowed_tool_names(),
            permission_mode="bypassPermissions",  # autonomous; isolation is the boundary
            max_turns=settings.max_turns,
            model=settings.model,
        )

        async for message in query(prompt=render_goal_prompt(job), options=options):
            await _stream_assistant_text(job, message)
    finally:
        # The SDK runs each tool handler in its own asyncio task with a COPIED
        # context, so a ContextVar flag set by finalize() can't signal back here.
        # Use the durable run as the cross-task completion signal instead.
        run = await store.get_run(job.id)
        if run is None or run.status != "done":
            await _auto_finalize(job)
        AGENT_CTX.reset(ctx_token)


async def _stream_assistant_text(job, message) -> None:
    if isinstance(message, AssistantMessage):
        for block in message.content:
            if isinstance(block, TextBlock) and block.text.strip():
                await store.emit_event(
                    EventEnvelope(
                        session_id=job.session_id,
                        job_id=job.id,
                        parent_job_id=job.parent_job_id,
                        depth=job.depth,
                        type=EventType.log,
                        payload={"text": block.text},
                    )
                )


async def _auto_finalize(job) -> None:
    """Safety net: the model ended without calling finalize. Synthesize a result
    from whatever children produced so the parent is never left hanging."""
    existing = await store.get_run(job.id)
    if existing and existing.status == "done":
        return  # a real finalize() already wrote the result; never clobber it
    children = await store.get_children_runs(job.id)
    summary = "Agent ended without an explicit finalize."
    metrics: dict = {}
    if children:
        best = max(children, key=lambda r: r.metrics.get("final_reward", float("-inf")))
        summary = f"(auto) Best child: {best.summary}"
        metrics = best.metrics
    run = RunResult(job_id=job.id, status="partial", summary=summary, metrics=metrics)
    await store.write_run(run)
    await store.set_job_status(job.id, JobStatus.done)
    await store.emit_event(
        EventEnvelope(
            session_id=job.session_id,
            job_id=job.id,
            parent_job_id=job.parent_job_id,
            depth=job.depth,
            type=EventType.summary,
            payload={"summary": summary, "metrics": metrics, "auto": True},
        )
    )
