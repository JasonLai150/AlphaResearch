"""Deterministic wandb run identity for a sub-agent.

SINGLE SOURCE OF TRUTH shared by the trainer (`init_wandb`) and the screenshot
tool (`screenshot_wandb.py`), so both always agree on WHICH run — even with many
sub-agents running at once. The run id is pinned to this sub-agent's job id, so:

    run id  = ALPHA_JOB_ID                (unique per sub-agent -> no collisions)
    entity  = WANDB_ENTITY               (must be the org the Browserbase context is logged into)
    project = WANDB_PROJECT or alpha-<session_id>
    url     = https://wandb.ai/<entity>/<project>/runs/<run id>   (deterministic)

`init_wandb()` also writes the canonical `run.url` to ALPHA_WORKSPACE/.wandb_run_url
so the screenshot tool can use wandb's own URL (authoritative) and fall back to the
derived convention if the trainer used plain `wandb.init`.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

RUN_URL_FILE = ".wandb_run_url"


def _slug(s: str) -> str:
    # wandb run ids / project names: alphanumeric + - and _ only.
    return re.sub(r"[^A-Za-z0-9_-]", "-", s).strip("-") or "run"


def _workspace() -> Path:
    return Path(os.environ.get("ALPHA_WORKSPACE", "/workspace"))


def run_identity() -> dict:
    """Compute this sub-agent's deterministic wandb identity from the environment."""
    job_id = os.environ.get("ALPHA_JOB_ID", "local")
    session_id = os.environ.get("ALPHA_SESSION_ID", "local")
    entity = os.environ.get("WANDB_ENTITY") or os.environ.get("ALPHA_WANDB_ENTITY") or ""
    project = os.environ.get("WANDB_PROJECT") or f"alpha-{_slug(session_id)}"
    run_id = _slug(job_id)
    idea_id = os.environ.get("ALPHA_IDEA_ID", "")
    url = f"https://wandb.ai/{entity}/{project}/runs/{run_id}" if entity else ""
    return {
        "job_id": job_id, "session_id": session_id, "idea_id": idea_id,
        "entity": entity, "project": project, "run_id": run_id, "url": url,
    }


def run_url_path() -> Path:
    return _workspace() / RUN_URL_FILE


def init_wandb(**overrides):
    """Start (or resume) THIS sub-agent's wandb run with a deterministic id, and
    record its canonical URL to ALPHA_WORKSPACE/.wandb_run_url.

    Use this instead of a bare ``wandb.init`` so the screenshot tool can always find
    the right run:

        from wandb_run import init_wandb
        run = init_wandb(config={...})
        ...  # log metrics as usual
    """
    import wandb  # lazy: only inside the sub-agent image

    ident = run_identity()
    kwargs = dict(
        id=ident["run_id"],
        name=ident["idea_id"] or ident["run_id"],
        group=ident["session_id"],
        resume="allow",
    )
    if ident["entity"]:
        kwargs["entity"] = ident["entity"]
    kwargs["project"] = ident["project"]
    kwargs.update(overrides)
    run = wandb.init(**kwargs)
    try:
        run_url_path().write_text((getattr(run, "url", "") or ident["url"]) + "\n")
    except OSError:
        pass
    return run


__all__ = ["run_identity", "init_wandb", "run_url_path", "RUN_URL_FILE"]
