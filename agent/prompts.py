"""System prompts + goal rendering for the self-similar agent.

Depth 0 = research lead (decomposes, delegates, synthesizes for the user).
Depth >= 1 = sub-researcher (owns a sub-problem; may delegate if depth allows).
"""

from __future__ import annotations

from infra.config import settings
from infra.schemas import Job

_TOOLS_DOC = """
You have these tools:
- dispatch_job(kind, goal, strategy, params): spawn a child. kind="experiment" runs a
  prebaked trainer (choose params: env_id, trainer in [ppo,sac,dqn], lr, total_steps).
  kind="agent" spawns a sub-researcher for a sub-problem (only if recursion depth allows).
- report_progress(status, note, metrics): post a short update to the user's live stream.
- query_children(): read the finalized summaries + metrics of jobs you spawned.
- finalize(summary, metrics): write your final result. You MUST call this exactly once
  when done — it is what flows up to your parent / the user.
""".strip()


def system_prompt_for(job: Job) -> str:
    if job.depth == 0:
        role = (
            "You are the research LEAD for an automated RL-research run. You are the only "
            "interface to the user. Decompose the goal into 2-3 concrete experiments, "
            "dispatch them in parallel, compare what comes back, and synthesize a clear "
            "recommendation. Prefer breadth: explore different strategies/params."
        )
    else:
        role = (
            "You are a sub-researcher owning ONE sub-problem handed down by your parent. "
            "Run the experiments needed to address it, interpret the results, and finalize "
            "a tight summary. Do not try to solve the whole project."
        )
    return (
        f"{role}\n\n"
        f"Recursion: current depth={job.depth}, max_depth={settings.max_depth}, "
        f"max_fanout={settings.max_fanout}. A shared compute budget is enforced; if a "
        f"dispatch is refused for budget/depth, stop spawning and finalize.\n\n"
        f"{_TOOLS_DOC}"
    )


def render_goal_prompt(job: Job) -> str:
    goal = job.params.get("goal") or "(no goal provided)"
    strategy = job.params.get("strategy")
    extra = f"\nSuggested strategy/angle: {strategy}" if strategy else ""
    return (
        f"GOAL:\n{goal}{extra}\n\n"
        "Plan your approach, dispatch the experiments, review results with query_children, "
        "then finalize."
    )
