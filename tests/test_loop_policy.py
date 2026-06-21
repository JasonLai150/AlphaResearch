"""The autonomous-loop stop policy — the single source of truth for whether a
loop continues or terminates, and why. Pure function over the loop record +
remaining budget; the runner calls it at each round boundary."""

from __future__ import annotations

from infra.loop_policy import decide
from infra.schemas import Loop, LoopStatus, RoundRecord


def _round(i: int, metric: float | None) -> RoundRecord:
    return RoundRecord(round_index=i, job_id=f"j_{i}", best_metric=metric, ended_at="t")


def _loop(rounds, *, max_rounds=5, goal_metric=None, plateau_k=3, stop_requested=False) -> Loop:
    return Loop(session_id="s", max_rounds=max_rounds, goal_metric=goal_metric,
                plateau_k=plateau_k, stop_requested=stop_requested, rounds=rounds)


def test_continue_when_nothing_triggers():
    d = decide(_loop([_round(1, 0.3), _round(2, 0.5)]), budget=100)
    assert d.action == "continue"


def test_stop_at_max_rounds():
    d = decide(_loop([_round(i, 0.1 * i) for i in range(1, 6)], max_rounds=5), budget=100)
    assert d.action == "stop"
    assert d.status == LoopStatus.completed
    assert "max_rounds" in d.reason


def test_stop_when_budget_exhausted():
    d = decide(_loop([_round(1, 0.3)]), budget=0)
    assert d.action == "stop"
    assert d.status == LoopStatus.budget_exhausted


def test_user_stop_takes_priority():
    # stop_requested wins even if other stop conditions also hold.
    d = decide(_loop([_round(1, 0.3)], stop_requested=True), budget=0)
    assert d.action == "stop"
    assert d.status == LoopStatus.stopped


def test_stop_when_goal_metric_reached():
    d = decide(_loop([_round(1, 0.4), _round(2, 0.91)], goal_metric=0.9), budget=100)
    assert d.action == "stop"
    assert d.status == LoopStatus.completed
    assert "target" in d.reason.lower() or "goal" in d.reason.lower()


def test_continue_when_goal_not_yet_reached():
    d = decide(_loop([_round(1, 0.4), _round(2, 0.7)], goal_metric=0.9), budget=100)
    assert d.action == "continue"


def test_stop_on_plateau():
    # plateau_k=2: last 2 rounds set no new high over the earlier rounds -> stop.
    rounds = [_round(1, 0.5), _round(2, 0.8), _round(3, 0.8), _round(4, 0.79)]
    d = decide(_loop(rounds, plateau_k=2, max_rounds=99), budget=100)
    assert d.action == "stop"
    assert d.status == LoopStatus.completed
    assert "improv" in d.reason.lower() or "plateau" in d.reason.lower()


def test_no_plateau_while_still_improving():
    rounds = [_round(1, 0.5), _round(2, 0.6), _round(3, 0.7), _round(4, 0.85)]
    d = decide(_loop(rounds, plateau_k=2, max_rounds=99), budget=100)
    assert d.action == "continue"


def test_plateau_needs_enough_rounds():
    # Fewer rounds than the window -> can't conclude plateau yet.
    d = decide(_loop([_round(1, 0.5), _round(2, 0.5)], plateau_k=3, max_rounds=99), budget=100)
    assert d.action == "continue"
