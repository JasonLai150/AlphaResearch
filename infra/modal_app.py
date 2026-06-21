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
# .entrypoint([]) clears the image's ENTRYPOINT: Modal runs from_dockerfile images via
# the inherited ENTRYPOINT, which would fire launch.py at container boot (before the
# function args exist) and crash with "missing ALPHA_JOB_ID". The sub_agent function
# invokes launch.py itself with the right env.
sub_image = modal.Image.from_dockerfile(
    "deploy/sub-agent.Dockerfile", context_dir=".", force_build=False,
).entrypoint([])

secret = modal.Secret.from_name("alpha-secrets")  # REDIS_URL, ANTHROPIC_API_KEY, GCS creds
app = modal.App(APP_NAME)


@app.function(image=image, timeout=3600, secrets=[secret], cpu=2.0, memory=2048)
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


@app.function(image=sub_image, timeout=600)
def warmup() -> str:
    """Deploy-time smoke + image warm-up (call via `modal run infra/modal_app.py::warmup`).
    Imports the heavy stack in the REAL sub-agent image so a broken/oversized image fails
    at deploy, not on the first user chat — and pre-pulls the image into Modal's cache.
    (The standing min_containers=1 sub_agent container is what primes the memory snapshot.)"""
    import envpool  # noqa: F401
    import torch  # noqa: F401
    return "warmup OK: torch + envpool import in sub_image"


# Resourcing (perf levers):
#  - cpu=8 / memory=8Gi: GUARANTEED cores so envpool can vectorize many envs (its whole
#    point) and PPO rollout buffers have headroom — without this Modal gives unguaranteed
#    burst CPU and env simulation can't parallelize (the dominant time sink). (Lever 1)
#  - scaledown_window=300: keep a finished container warm 5 min so a fan-out burst /
#    iterative re-dispatch reuses it instead of cold-starting each time; scales to 0 after
#    (no idle cost between sessions). Bump min_containers>0 for a standing warm pool. (Lever 2)
#  - enable_memory_snapshot: restore container init from a snapshot instead of re-running
#    it on every cold start. Validate on first deploy. (Lever 2)
@app.function(
    image=sub_image,
    timeout=3600 * 2,
    secrets=[secret],
    cpu=8.0,
    memory=8192,
    scaledown_window=300,
    enable_memory_snapshot=True,
    # Demo: keep ONE container always warm so the first chat skips the image
    # pull + snapshot-restore cold start. Concurrent fan-out beyond 1 still cold-starts;
    # raise to the demo's idea-count for all-instant (at idle cost). Scale to 0 after the
    # demo by removing this. The post-deploy warm-up spawn (deploy_modal.sh) primes the snapshot.
    min_containers=1,
)
def sub_agent(
    job_id: str,
    session_id: str,
    internal_token: str = "",
    internal_runner_url: str = "",
    dispatch_record: str = "",
    traceparent: str = "",
    baggage: str = "",
    wandb_entity: str = "",
    browserbase_context_id: str = "",
    browserbase_project_id: str = "",
) -> None:
    """Boot the Claude Code sub-agent.

    PR2: no shared volume. The dispatch record arrives as ``dispatch_record`` (JSON) and
    is written into this container's own /workspace/.dispatched/<jid>.json so the agent
    reads its plan/idea exactly as its CLAUDE.md describes. Results + artifacts are pushed
    back over HTTP (the finalize hook POSTs /internal/result) — nothing flows via Modal."""
    import json as _json
    import os as _os
    import shutil as _shutil

    _AGENT = "agent"  # non-root user baked into the image (claude blocks root)
    disp = "/workspace/.dispatched"
    _os.makedirs(disp, exist_ok=True)
    if dispatch_record:
        # validate it's JSON, then write the record the sub-agent reads on boot.
        _json.loads(dispatch_record)
        with open(_os.path.join(disp, f"{job_id}.json"), "w") as f:
            f.write(dispatch_record)
    # The function runs as root on Modal; hand the dispatch dir to the agent user so the
    # non-root sub-agent can read its record and write artifacts under it.
    for root_dir, _dirs, files in _os.walk(disp):
        _shutil.chown(root_dir, _AGENT, _AGENT)
        for n in files:
            _shutil.chown(_os.path.join(root_dir, n), _AGENT, _AGENT)

    env = os.environ.copy()
    env["ALPHA_JOB_ID"] = job_id
    env["ALPHA_SESSION_ID"] = session_id
    env["ALPHA_DEPTH"] = "1"
    env["ALPHA_WORKSPACE"] = "/workspace"
    env["ALPHA_DISPATCH_DIR"] = disp
    env["HOME"] = "/home/agent"  # ~/.claude for the non-root user
    if internal_token:
        env["ALPHA_INTERNAL_TOKEN"] = internal_token
    if internal_runner_url:
        env["ALPHA_INTERNAL_RUNNER_URL"] = internal_runner_url
    if traceparent:
        env["TRACEPARENT"] = traceparent
    if baggage:
        env["TRACESTATE"] = baggage
    # Static OTEL config (CLAUDE_CODE_ENABLE_TELEMETRY, OTEL_EXPORTER_OTLP_*, content
    # flags) arrives via the alpha-secrets Modal secret (see scripts/deploy_modal.sh),
    # not here. traceparent/baggage above are the per-exec W3C trace context (Layer A).

    # Intentionally NOT Sentry-instrumented: sub_image is built from deploy/sub-agent.Dockerfile
    # and does not carry infra/. Visibility comes via runner/internal-API spans.

    # wandb run identity + Browserbase context for deterministic per-run screenshots
    # (scripts/capture_wandb.py). WANDB_PROJECT defaults to alpha-<session_id> in
    # scripts/wandb_run.py. BROWSERBASE_API_KEY + WANDB_API_KEY come from alpha-secrets.
    if wandb_entity:
        env["WANDB_ENTITY"] = wandb_entity
    if browserbase_context_id:
        env["BROWSERBASE_CONTEXT_ID"] = browserbase_context_id
    if browserbase_project_id:
        env["BROWSERBASE_PROJECT_ID"] = browserbase_project_id

    # Same headless launcher the sub-agent Dockerfile ENTRYPOINT uses (Modal overrides
    # the image entrypoint, so we invoke it explicitly): builds the prompt from the
    # dispatch record and execs `claude -p`, as the non-root `agent` user.
    subprocess.run(["python3", "launch.py"], cwd="/workspace", env=env, check=False,
                   user=_AGENT)
