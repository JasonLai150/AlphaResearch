"""The autonomous-loop stop policy — the single source of truth for whether a
research loop continues or terminates, and why.

Pure function over the loop record + remaining budget; the runner calls it at
each round boundary (after a round's agent exits) and either spawns the next
round or marks the loop terminal. Keeping this here (not in agent prose) makes
"keep going vs stop" deterministic, testable, and outside the model's whim.

Higher `best_metric` is assumed better (the target metric is maximized).
"""

from __future__ import annotations

from dataclasses import dataclass

from infra.schemas import Loop, LoopStatus


@dataclass(frozen=True)
class LoopDecision:
    action: str                 # "continue" | "stop"
    status: LoopStatus | None   # the terminal status to set, when action == "stop"
    reason: str


def _continue() -> LoopDecision:
    return LoopDecision("continue", None, "")


def _stop(status: LoopStatus, reason: str) -> LoopDecision:
    return LoopDecision("stop", status, reason)


def _metrics(loop: Loop) -> list[float]:
    return [r.best_metric for r in loop.rounds if r.best_metric is not None]


def _plateaued(loop: Loop) -> bool:
    """No new best over the last ``plateau_k`` rounds (and there were earlier rounds
    to improve on)."""
    k = loop.plateau_k
    metrics = _metrics(loop)
    if k <= 0 or len(metrics) <= k:
        return False
    window, earlier = metrics[-k:], metrics[:-k]
    return max(window) <= max(earlier)


def decide(loop: Loop, budget: int) -> LoopDecision:
    """Evaluate the stop policy. Order matters: user-stop and budget are hard halts
    that win over anything else."""
    if loop.stop_requested:
        return _stop(LoopStatus.stopped, "stop requested by user")
    if budget <= 0:
        return _stop(LoopStatus.budget_exhausted, "session budget exhausted")

    completed = len(loop.rounds)
    if completed >= loop.max_rounds:
        return _stop(LoopStatus.completed, f"reached max_rounds={loop.max_rounds}")

    if loop.goal_metric is not None and loop.rounds:
        latest = loop.rounds[-1].best_metric
        if latest is not None and latest >= loop.goal_metric:
            return _stop(LoopStatus.completed,
                         f"target metric reached ({latest} >= {loop.goal_metric})")

    if _plateaued(loop):
        return _stop(LoopStatus.completed,
                     f"no improvement over last {loop.plateau_k} rounds")

    return _continue()
