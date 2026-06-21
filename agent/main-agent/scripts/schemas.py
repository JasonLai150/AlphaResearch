"""Pydantic schemas for the research plan and ideas.

This module is the SINGLE source of truth for what a valid dispatch payload
looks like. Both the deterministic dispatch script and the PreToolUse hook
import from here, so a malformed plan is rejected the same way at both
gates.

Standalone on purpose: no infra/ imports. The main-agent container only needs
this file + pydantic to validate.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

# ---- demo guardrails (small, fast, low-variance search space) ----------------
# The prebaked trainer (agent/sub-agent/scripts/train_ppo.py) runs ONE tested PPO on a
# fixed tiny env; an "idea" is a set of hyperparameter overrides. These caps keep every
# run to seconds and bound the search space. The PreToolUse dispatch hook validates a
# plan against this schema, so the main agent CANNOT dispatch out-of-bounds work.
ALLOWED_ENVS = {"MiniGrid-Empty-5x5-v0"}
MAX_BUDGET_STEPS = 50_000
# Hyperparameter knobs train_ppo.py exposes (must match its TUNABLE). base_hparams +
# idea interventions stay within these so the agent parameterizes, never authors code.
TUNABLE_KNOBS = {
    "learning_rate", "ent_coef", "num_steps", "gamma", "gae_lambda", "clip_coef",
    "vf_coef", "max_grad_norm", "update_epochs", "num_minibatches", "hidden_size",
    "norm_adv", "anneal_lr",
}


class DiversityTag(StrEnum):
    """Coarse buckets that force ideas to attack different parts of the system.
    The plan validator rejects plans where one tag dominates (>ceil(n/2))."""

    exploration = "exploration"        # entropy schedules, novelty bonuses, RND, ICM
    reward_shaping = "reward_shaping"  # potential-based shaping, curriculum, intrinsic
    architecture = "architecture"      # encoder, recurrence, attention
    optimizer = "optimizer"            # lr schedules, clip range, advantage norm
    regularization = "regularization"  # dropout, weight decay, KL targets
    data = "data"                      # replay, augmentation, frame stacking
    algorithm = "algorithm"            # core algo change (PPO -> APPO/IMPALA/DAPO)
    other = "other"


class ResearchIdea(BaseModel):
    """One sub-agent's niche. Differs from siblings, shares the plan scaffold."""

    id: str = Field(default_factory=lambda: f"idea_{uuid.uuid4().hex[:6]}")
    title: str                                    # short kebab tag
    diversity_tag: DiversityTag                   # axis this idea moves
    hypothesis: str                               # 1-3 sentences: what we expect + why
    approach: str                                 # concrete intervention
    success_criterion: str                        # observable result that validates it
    expected_metric_delta: float | None = None

    @field_validator("title", "hypothesis", "approach", "success_criterion")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must be non-empty")
        return v


class ResearchPlan(BaseModel):
    """Consistency scaffold (FROZEN across sub-agents) + 2-5 diverse ideas.

    Every dispatched sub-agent receives the whole plan plus one assigned
    idea_id, so it can see its siblings but only optimizes its own niche.
    """

    id: str = Field(default_factory=lambda: f"plan_{uuid.uuid4().hex[:8]}")
    goal: str
    env_id: str                                   # must be in ALLOWED_ENVS (demo guardrail)
    reward_fn_spec: str                           # FROZEN reward, described in prose
    base_hparams: dict                            # FROZEN, non-empty, keys ⊆ TUNABLE_KNOBS
    target_metric: str                            # SINGLE scalar to optimize
    budget_steps: int = Field(gt=0, le=MAX_BUDGET_STEPS)  # per-sub-agent budget (capped)
    # Single source of truth for TIME (idea 3). The wall-clock a sub-agent may need to
    # burn budget_steps on a CPU learner. The main agent derives its wait_for_children
    # timeout from this (so it doesn't synthesize before slow children land), and it
    # bounds the runner's synthesis barrier. Optional: omit and the agent falls back to
    # the wait script's default. Capped at the Modal sub-agent timeout (2h).
    wall_clock_budget_seconds: int | None = Field(default=None, gt=0)
    ideas: list[ResearchIdea]

    def wait_timeout_seconds(self, default: int = 7200) -> int:
        """The timeout the main agent should pass to wait_for_children: the explicit
        wall-clock budget if set, else a sane default, hard-capped at Modal's 2h cap."""
        return min(self.wall_clock_budget_seconds or default, 7200)

    @field_validator("goal", "env_id", "reward_fn_spec", "target_metric")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must be non-empty")
        return v

    @field_validator("env_id")
    @classmethod
    def _env_allowed(cls, v: str) -> str:
        v = v.strip()
        if v not in ALLOWED_ENVS:
            raise ValueError(
                f"env_id must be one of {sorted(ALLOWED_ENVS)} (demo guardrail); got {v!r}"
            )
        return v

    @field_validator("base_hparams")
    @classmethod
    def _base_hparams_valid(cls, v: dict) -> dict:
        if not v:
            raise ValueError("base_hparams must be non-empty (locks the comparison)")
        unknown = set(v) - TUNABLE_KNOBS
        if unknown:
            raise ValueError(
                f"base_hparams has unsupported knobs {sorted(unknown)}; the prebaked "
                f"trainer only accepts {sorted(TUNABLE_KNOBS)}"
            )
        return v

    @model_validator(mode="after")
    def _ideas_diverse(self) -> ResearchPlan:
        n = len(self.ideas)
        if n < 2 or n > 5:
            raise ValueError(f"plan must have 2-5 ideas, got {n}")
        ids = [i.id for i in self.ideas]
        if len(set(ids)) != n:
            raise ValueError("idea ids must be unique")
        titles = [i.title.lower().strip() for i in self.ideas]
        if len(set(titles)) != n:
            raise ValueError("idea titles must be unique")
        tags = [i.diversity_tag for i in self.ideas]
        cap = max(1, (n + 1) // 2)
        if max(tags.count(t) for t in set(tags)) > cap:
            raise ValueError(
                "ideas not diverse enough: one diversity_tag dominates "
                f"(tags={[t.value for t in tags]}, cap_per_tag={cap})"
            )
        return self

    def find_idea(self, idea_id: str) -> ResearchIdea | None:
        return next((i for i in self.ideas if i.id == idea_id), None)


class GraphKind(StrEnum):
    """Chart kinds render_graph.py knows how to draw deterministically."""

    line = "line"        # training curves, metric-vs-steps
    bar = "bar"          # per-idea deltas vs baseline
    scatter = "scatter"  # x/y relationships (e.g. cost vs return)


class GraphSeries(BaseModel):
    """One named trace. The agent supplies DATA ONLY — never colors or styling."""

    name: str
    x: list[float | str]  # numeric (steps) OR categorical labels (idea names for bars)
    y: list[float]
    error_y: list[float] | None = None  # optional symmetric error bars (e.g. seed std)

    @field_validator("name")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("series name must be non-empty")
        return v

    @model_validator(mode="after")
    def _lengths_match(self) -> GraphSeries:
        if len(self.x) != len(self.y):
            raise ValueError(
                f"series '{self.name}': x and y must be equal length "
                f"(x={len(self.x)}, y={len(self.y)})"
            )
        if self.error_y is not None and len(self.error_y) != len(self.y):
            raise ValueError(
                f"series '{self.name}': error_y must match y length "
                f"(error_y={len(self.error_y)}, y={len(self.y)})"
            )
        return self


class GraphSpec(BaseModel):
    """Declarative graph the main agent writes to ``.graphs/specs/<id>.json``.

    Pure content: chart kind, labels, and data series. ALL styling (theme, colors,
    fonts, layout) is owned by render_graph.py, so the same spec always renders the
    same beautiful Plotly figure — determinism by construction. A PostToolUse hook
    validates this shape on write; render_graph.py re-validates before drawing.
    """

    schema_version: int = 1
    id: str                              # kebab slug; also the output filename
    kind: GraphKind
    title: str
    x_label: str = ""
    y_label: str = ""
    series: list[GraphSeries]
    caption: str | None = None
    meta: dict = Field(default_factory=dict)  # provenance: env_id, target_metric, job ids

    @field_validator("id", "title")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must be non-empty")
        return v

    @field_validator("series")
    @classmethod
    def _at_least_one(cls, v: list) -> list:
        if not v:
            raise ValueError("a graph needs at least one series")
        return v


__all__ = [
    "DiversityTag", "ResearchIdea", "ResearchPlan",
    "GraphKind", "GraphSeries", "GraphSpec",
    "ALLOWED_ENVS", "MAX_BUDGET_STEPS", "TUNABLE_KNOBS",
]
