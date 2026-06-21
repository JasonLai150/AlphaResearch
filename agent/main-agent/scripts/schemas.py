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
    env_id: str                                   # e.g. "MiniGrid-DoorKey-8x8"
    reward_fn_spec: str                           # FROZEN reward, described in prose
    base_hparams: dict                            # FROZEN, must be non-empty
    target_metric: str                            # SINGLE scalar to optimize
    budget_steps: int = Field(gt=0)               # per-sub-agent training budget
    ideas: list[ResearchIdea]

    @field_validator("goal", "env_id", "reward_fn_spec", "target_metric")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must be non-empty")
        return v

    @field_validator("base_hparams")
    @classmethod
    def _base_hparams_nonempty(cls, v: dict) -> dict:
        if not v:
            raise ValueError("base_hparams must be non-empty (locks the comparison)")
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


__all__ = ["DiversityTag", "ResearchIdea", "ResearchPlan"]
