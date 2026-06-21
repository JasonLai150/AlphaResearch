"""Modal app: the prebaked experiment image + the sub-agent harness function.

Deploy with `modal deploy infra/modal_app.py`.

Two functions live here:
  * ``run_job``   — runs a non-agentic EXPERIMENT job in a sandbox (DISPATCH_BACKEND=modal).
  * ``sub_agent`` — boots the Claude Code CLI sub-agent (one per dispatched idea). The
                    runner mounts the per-session Volume at /workspace/.dispatched and
                    injects the per-session token; the sub-agent reads its dispatch record,
                    runs, and its finalize hook writes result.json + a .done sentinel into
                    that volume. We commit the volume on exit so the runner sees the writes.

The MAIN agent is NOT here — it runs as a Cloud Run Job (deploy/main-agent.Dockerfile),
launched by runner/cloud_run_client.py. Modal hosts sub-agents only.
"""

from __future__ import annotations

import os
import subprocess

import modal

APP_NAME = "alpharesearch"

# Prebaked experiment image (synthetic-experiment deps; heavy ML stack added later).
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "claude-agent-sdk",
        "redis>=5.2",
        "google-cloud-storage",
        "pydantic>=2.9",
        "pydantic-settings",
        "httpx",
        "tenacity",
        "orjson",
        "sentry-sdk[fastapi]>=2.35",
        "numpy",
        "matplotlib",
    )
    .add_local_python_source("agent", "infra")
)

# Sub-agent image: the Claude Code CLI + RL stack + the agent/sub-agent workspace,
# built from the same Dockerfile the Cloud Run / docker paths use.
sub_image = modal.Image.from_dockerfile(
    "deploy/sub-agent.Dockerfile", context_dir=".", force_build=False,
)

secret = modal.Secret.from_name("alpha-secrets")  # REDIS_URL, ANTHROPIC_API_KEY, GCS creds
app = modal.App(APP_NAME)


@app.function(image=image, timeout=3600, secrets=[secret])
async def run_job(job_id: str) -> None:
    """Entrypoint inside a Modal sandbox: run a prebaked experiment job."""
    from infra.observability import init_observability
    init_observability("modal-experiment")

    from infra import store
    from infra.schemas import JobKind

    job = await store.get_job(job_id)
    if job is None:
        raise ValueError(f"unknown job {job_id}")
    if job.kind == JobKind.experiment:
        from infra.registry.experiment import run_experiment_real

        await run_experiment_real(job)
    else:
        raise NotImplementedError(
            f"agent-kind job {job_id} must be launched by the runner, not run_job"
        )


async def spawn_job(job_id: str) -> str:
    """Spawn run_job; return the Modal call id. Async (.spawn.aio) — callers run in
    an asyncio loop where blocking .spawn() can stall the event loop."""
    try:
        call = await run_job.spawn.aio(job_id)
    except Exception:
        fn = modal.Function.from_name(APP_NAME, "run_job")
        call = await fn.spawn.aio(job_id)
    return call.object_id


@app.function(image=sub_image, timeout=3600 * 2, secrets=[secret])
def sub_agent(
    job_id: str,
    session_id: str,
    internal_token: str = "",
    internal_runner_url: str = "",
) -> None:
    """Boot the Claude Code sub-agent. The per-session volume is mounted at
    /workspace/.dispatched by the runner at spawn time."""
    # Intentionally NOT Sentry-instrumented: sub_image is built from deploy/sub-agent.Dockerfile
    # and does not carry infra/; visibility comes via runner/internal-API spans (Tasks 3-4).
    env = os.environ.copy()
    env["ALPHA_JOB_ID"] = job_id
    env["ALPHA_SESSION_ID"] = session_id
    env["ALPHA_DEPTH"] = "1"
    env["ALPHA_WORKSPACE"] = "/workspace"
    env["ALPHA_DISPATCH_DIR"] = "/workspace/.dispatched"
    if internal_token:
        env["ALPHA_INTERNAL_TOKEN"] = internal_token
    if internal_runner_url:
        env["ALPHA_INTERNAL_RUNNER_URL"] = internal_runner_url

    subprocess.run(["claude", "--dangerously-skip-permissions"], cwd="/workspace",
                   env=env, check=False)

    # Flush result.json + .done sentinel + artifacts back to the volume so the
    # runner's reconcile loop can read them.
    try:
        modal.Volume.from_name(f"alpha-session-{session_id}").commit()
    except Exception:
        pass
