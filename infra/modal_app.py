"""Modal app: the prebaked image + the function that runs a job (agent or
experiment) at depth >= 1. Deploy with `modal deploy infra/modal_app.py` so
`run_job` is addressable for nested spawn. Used only when DISPATCH_BACKEND=modal;
the local backend never imports this module.

Phase 2 TODO: implement infra.registry.experiment.run_experiment_real against the
real prebaked envs/trainers carried by this image, and validate nested spawn.
"""

from __future__ import annotations

import modal

APP_NAME = "alpharesearch"

# Prebaked image: the ML/sim stack + our runtime deps + our source code.
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        # Lean image for a fast, robust first deploy: runtime + synthetic-experiment
        # deps only. The heavy ML stack (torch/gymnasium/minigrid/envpool) is added
        # when run_experiment_real does real training — not needed for the P0
        # spawn -> report -> aggregate round-trip.
        "claude-agent-sdk",
        "redis>=5.2",
        "google-cloud-storage",
        "pydantic>=2.9",
        "pydantic-settings",
        "httpx",
        "tenacity",
        "orjson",
        "numpy",
        "matplotlib",
    )
    .add_local_python_source("agent", "infra")
)

app = modal.App(APP_NAME)


@app.function(
    image=image,
    timeout=3600,
    secrets=[modal.Secret.from_name("alpha-secrets")],  # REDIS_URL, ANTHROPIC_API_KEY, GCS creds
)
async def run_job(job_id: str) -> None:
    """Self-similar entrypoint inside a Modal sandbox: dispatch by job kind."""
    from infra import store
    from infra.schemas import JobKind

    job = await store.get_job(job_id)
    if job is None:
        raise ValueError(f"unknown job {job_id}")
    if job.kind == JobKind.experiment:
        from infra.registry.experiment import run_experiment_real

        await run_experiment_real(job)
    else:
        from agent.run_agent import run_agent

        await run_agent(job_id)


async def spawn_job(job_id: str) -> str:
    """Spawn run_job, return the Modal call id. Async (.spawn.aio) — callers run inside
    an asyncio loop, where blocking .spawn() warns and can stall the event loop. Works
    both from the local/Cloud Run reference and nested inside Modal (resolve by name)."""
    try:
        call = await run_job.spawn.aio(job_id)
    except Exception:
        fn = modal.Function.from_name(APP_NAME, "run_job")
        call = await fn.spawn.aio(job_id)
    return call.object_id
