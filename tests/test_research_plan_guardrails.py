"""Demo guardrails on ResearchPlan (agent/main-agent/scripts/schemas.py).

The PreToolUse dispatch hook validates every plan against this schema, so an
out-of-bounds plan (wrong env, over budget, non-knob base_hparams) is rejected at the
gate and the main agent can't dispatch runaway work.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent / "agent" / "main-agent" / "scripts")
)
from schemas import ALLOWED_ENVS, MAX_BUDGET_STEPS, ResearchPlan  # noqa: E402


def _plan(**over) -> dict:
    base = {
        "goal": "improve sample efficiency",
        "env_id": "MiniGrid-Empty-5x5-v0",
        "reward_fn_spec": "sparse +1 on reaching the goal, frozen",
        "base_hparams": {"learning_rate": 2.5e-4, "ent_coef": 0.01},
        "target_metric": "mean_return_at_50k_steps",
        "budget_steps": 50000,
        "ideas": [
            {"title": "higher-entropy", "diversity_tag": "exploration", "hypothesis": "h",
             "approach": "ent_coef=0.05", "success_criterion": "faster solve"},
            {"title": "bigger-lr", "diversity_tag": "optimizer", "hypothesis": "h",
             "approach": "learning_rate=1e-3", "success_criterion": "faster solve"},
        ],
    }
    base.update(over)
    return base


def test_valid_demo_plan_passes():
    p = ResearchPlan.model_validate(_plan())
    assert p.env_id in ALLOWED_ENVS
    assert p.budget_steps <= MAX_BUDGET_STEPS


def test_rejects_non_allowlisted_env():
    with pytest.raises(ValidationError):
        ResearchPlan.model_validate(_plan(env_id="MiniGrid-DoorKey-8x8-v0"))


def test_rejects_over_budget():
    with pytest.raises(ValidationError):
        ResearchPlan.model_validate(_plan(budget_steps=MAX_BUDGET_STEPS + 1))


def test_rejects_unknown_base_hparam_knobs():
    # "lr"/"n_steps" are not the trainer's knob names (learning_rate/num_steps)
    with pytest.raises(ValidationError):
        ResearchPlan.model_validate(_plan(base_hparams={"lr": 3e-4, "n_steps": 128}))


def test_accepts_valid_knobs_including_bools():
    p = ResearchPlan.model_validate(
        _plan(base_hparams={"learning_rate": 1e-3, "norm_adv": False, "hidden_size": 128}))
    assert p.base_hparams["norm_adv"] is False
