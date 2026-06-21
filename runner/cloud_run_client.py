"""Cloud Run Jobs client for the main-agent path.

The runner triggers one Cloud Run Job *execution* per chat (main agent). The
execution name is stored as ``Job.sandbox_id`` and polled for completion. The
per-session ephemeral token (SEV-4) is injected as a **per-execution container
override** — never baked into the Job spec — so a token only ever grants access
to its own session and rotates per run.
"""

from __future__ import annotations

from typing import Literal

from infra import store
from infra.config import settings

_jobs_client = None
_execs_client = None


def _jobs():
    global _jobs_client
    if _jobs_client is None:
        from google.cloud import run_v2
        _jobs_client = run_v2.JobsAsyncClient()
    return _jobs_client


def _execs():
    global _execs_client
    if _execs_client is None:
        from google.cloud import run_v2
        _execs_client = run_v2.ExecutionsAsyncClient()
    return _execs_client


async def spawn_main_agent_job(session_id: str, job_id: str) -> str:
    """Trigger a main-agent Cloud Run Job execution. Returns the execution name
    (used as Job.sandbox_id). Raises if the LRO yields no execution name so the
    caller never records sandbox_id=None and then xdels the queue entry (SEV-9)."""
    from google.cloud import run_v2

    token = await store.get_session_token(session_id)  # SEV-4: per-session, per-exec
    name = (
        f"projects/{settings.gcp_project}/locations/{settings.gcp_region}"
        f"/jobs/{settings.main_agent_job_name}"
    )
    overrides = run_v2.RunJobRequest.Overrides(
        container_overrides=[
            run_v2.RunJobRequest.Overrides.ContainerOverride(
                env=[
                    run_v2.EnvVar(name="ALPHA_SESSION_ID", value=session_id),
                    run_v2.EnvVar(name="ALPHA_JOB_ID", value=job_id),
                    run_v2.EnvVar(name="ALPHA_DEPTH", value="0"),
                    run_v2.EnvVar(name="ALPHA_MODEL", value=settings.model),
                    run_v2.EnvVar(name="ALPHA_INTERNAL_TOKEN", value=token),
                    run_v2.EnvVar(
                        name="ALPHA_INTERNAL_RUNNER_URL", value=settings.internal_runner_url
                    ),
                    # The goal is NOT injected here — the agent fetches it from
                    # GET /internal/bootstrap (token->session), so the conversational
                    # future can return a refined goal/transcript via the same seam.
                ],
            )
        ],
    )
    op = await _jobs().run_job(run_v2.RunJobRequest(name=name, overrides=overrides))
    metadata = getattr(op, "metadata", None)
    exec_name = getattr(metadata, "name", None) if metadata is not None else None
    if not exec_name:
        # SEV-9: google-cloud-run may return a lazy/None metadata.name. Recording
        # sandbox_id=None would make poll throw forever and strand the job.
        raise RuntimeError(
            "Cloud Run run_job returned no execution name (op.metadata.name); "
            "refusing to record sandbox_id=None"
        )
    return exec_name


async def poll_cloud_run_exec(execution_name: str) -> Literal["running", "done", "failed"]:
    execution = await _execs().get_execution(name=execution_name)
    if getattr(execution, "completion_time", None):
        return "done" if getattr(execution, "succeeded_count", 0) else "failed"
    return "running"
