"""Typed contracts — the stable API between the swappable research-loop layer
and the fixed infra layer (plan §2.5). Versioned: bump SCHEMA_VERSION on any
breaking change to these shapes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# v2: Job gains backend+sandbox_id, drops modal_call_id; adds Message; +queued/+cancelled status
SCHEMA_VERSION = 2


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobKind(StrEnum):
    agent = "agent"            # a recursive sub-researcher (runs run_agent)
    experiment = "experiment"  # a non-agentic prebaked training/eval run


class JobStatus(StrEnum):
    pending = "pending"
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    cancelled = "cancelled"


class EventType(StrEnum):
    log = "log"
    metric = "metric"
    status = "status"
    spawn = "spawn"
    artifact = "artifact"
    summary = "summary"


class Session(BaseModel):
    id: str
    user_id: str
    goal: str
    # "oneshot": derive the plan from `goal` alone and dispatch (PR1). "conversational":
    # the goal is refined over user<->main-agent turns before dispatch (future). The
    # main agent reads this via GET /internal/bootstrap and gates its clarifying-questions
    # step on it.
    mode: str = "oneshot"
    status: str = "running"
    created_at: str = Field(default_factory=_now)


class Job(BaseModel):
    id: str
    session_id: str
    parent_job_id: str | None = None
    depth: int = 0
    kind: JobKind = JobKind.agent
    status: JobStatus = JobStatus.pending
    params: dict = Field(default_factory=dict)  # includes goal/strategy/env_id/hparams
    gpu: bool = False
    backend: str = "modal"        # "modal" | "cloud_run_job" | "local"
    sandbox_id: str | None = None  # Modal FunctionCall.object_id OR Cloud Run execution name
    created_at: str = Field(default_factory=_now)


class Message(BaseModel):
    """One turn in the chat transcript. Written by the agent log_transcript hook
    via HTTP POST to /internal/transcript, stored on a per-session Redis Stream."""

    session_id: str
    job_id: str
    role: str  # user | assistant | tool_use | tool_result | system
    content: str = ""
    tool_name: str | None = None
    tool_input: dict | None = None
    ts: str = Field(default_factory=_now)


class DispatchPayload(BaseModel):
    """What a parent passes to spawn a child (via the dispatch_job tool)."""

    kind: JobKind
    goal: str = ""
    strategy: str = ""
    params: dict = Field(default_factory=dict)
    gpu: bool = False
    cost: int = 1


class RunResult(BaseModel):
    """A job's final result. Flows UP to the parent (and to the UI)."""

    job_id: str
    status: str = "done"  # done | failed | partial
    summary: str = ""
    metrics: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now)


class ArtifactRef(BaseModel):
    id: str
    job_id: str
    kind: str  # plot | checkpoint | log | other
    url: str   # gs://... in prod, or a local /artifacts/... path in dev
    caption: str | None = None
    bytes: int = 0


class EventEnvelope(BaseModel):
    """One message on the per-session event bus (Redis Stream)."""

    session_id: str
    job_id: str
    parent_job_id: str | None = None
    depth: int = 0
    type: EventType
    payload: dict = Field(default_factory=dict)
    ts: str = Field(default_factory=_now)
    v: int = SCHEMA_VERSION
