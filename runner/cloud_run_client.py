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


async def spawn_main_agent_job(
    session_id: str, job_id: str, *, traceparent: str = "", baggage: str = ""
) -> str:
    """Trigger a main-agent Cloud Run Job execution. Returns the execution name
    (used as Job.sandbox_id). Raises if the LRO yields no execution name so the
    caller never records sandbox_id=None and then xdels the queue entry (SEV-9).

    When agent OTEL is enabled (settings.agent_otel_enabled + an OTLP endpoint),
    injects Claude Code's native-telemetry env vars + W3C trace context so the agent's
    OTEL traces export to Sentry, correlated by alpha.session_id/alpha.job_id."""
    from google.cloud import run_v2

    token = await store.get_session_token(session_id)  # SEV-4: per-session, per-exec
    name = (
        f"projects/{settings.gcp_project}/locations/{settings.gcp_region}"
        f"/jobs/{settings.main_agent_job_name}"
    )
    env = [
        run_v2.EnvVar(name="ALPHA_SESSION_ID", value=session_id),
        run_v2.EnvVar(name="ALPHA_JOB_ID", value=job_id),
        run_v2.EnvVar(name="ALPHA_DEPTH", value="0"),
        run_v2.EnvVar(name="ALPHA_MODEL", value=settings.model),
        run_v2.EnvVar(name="ALPHA_INTERNAL_TOKEN", value=token),
        run_v2.EnvVar(name="ALPHA_INTERNAL_RUNNER_URL", value=settings.internal_runner_url),
        # The goal is NOT injected here — the agent fetches it from
        # GET /internal/bootstrap (token->session), so the conversational
        # future can return a refined goal/transcript via the same seam.
    ]
    if settings.agent_otel_enabled and settings.otel_otlp_endpoint:
        env += [
            run_v2.EnvVar(name="CLAUDE_CODE_ENABLE_TELEMETRY", value="1"),
            run_v2.EnvVar(name="CLAUDE_CODE_ENHANCED_TELEMETRY_BETA", value="1"),
            run_v2.EnvVar(name="OTEL_TRACES_EXPORTER", value="otlp"),
            run_v2.EnvVar(name="OTEL_LOGS_EXPORTER", value="otlp"),
            run_v2.EnvVar(name="OTEL_EXPORTER_OTLP_PROTOCOL", value="http/protobuf"),
            run_v2.EnvVar(name="OTEL_EXPORTER_OTLP_ENDPOINT", value=settings.otel_otlp_endpoint),
            run_v2.EnvVar(name="OTEL_LOG_USER_PROMPTS", value="true"),
            run_v2.EnvVar(name="OTEL_LOG_TOOL_DETAILS", value="true"),
            run_v2.EnvVar(name="OTEL_LOG_TOOL_CONTENT", value="true"),
            run_v2.EnvVar(
                name="OTEL_RESOURCE_ATTRIBUTES",
                value=f"alpha.session_id={session_id},alpha.job_id={job_id},alpha.depth=0",
            ),
        ]
        if settings.otel_otlp_headers:
            env.append(run_v2.EnvVar(name="OTEL_EXPORTER_OTLP_HEADERS",
                                     value=settings.otel_otlp_headers))
        if traceparent:
            env.append(run_v2.EnvVar(name="TRACEPARENT", value=traceparent))
        if baggage:
            env.append(run_v2.EnvVar(name="TRACESTATE", value=baggage))
    overrides = run_v2.RunJobRequest.Overrides(
        container_overrides=[run_v2.RunJobRequest.Overrides.ContainerOverride(env=env)],
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


_log_client = None


def _logs():
    global _log_client
    if _log_client is None:
        from google.cloud import logging_v2
        _log_client = logging_v2.services.logging_service_v2.LoggingServiceV2AsyncClient()
    return _log_client


async def fetch_exec_logs(execution_name: str, *, limit: int = 40) -> list[str]:
    """Best-effort tail of a Cloud Run Job execution's stdout/stderr from Cloud
    Logging, oldest→newest. Returns [] on any error — this is surfaced to chat for
    diagnosis and must never break the reconcile path that calls it.

    `execution_name` is the full resource path; Cloud Logging labels it by the
    short execution id (the last path segment)."""
    try:
        exec_id = execution_name.rsplit("/", 1)[-1]
        # Project is parsed from the execution path so we never depend on settings drift.
        project = execution_name.split("/", 2)[1] if execution_name.startswith("projects/") \
            else settings.gcp_project
        flt = (
            'resource.type="cloud_run_job" '
            f'AND labels."run.googleapis.com/execution_name"="{exec_id}"'
        )
        resp = await _logs().list_log_entries(request={
            "resource_names": [f"projects/{project}"],
            "filter": flt,
            "order_by": "timestamp desc",
            "page_size": limit,
        })
        lines: list[str] = []
        async for entry in resp:
            text = entry.text_payload or ""
            if not text and entry.json_payload:
                text = str(dict(entry.json_payload).get("message", "")) or str(dict(entry.json_payload))
            text = text.strip()
            if text:
                lines.append(text)
            if len(lines) >= limit:
                break
        lines.reverse()  # list_log_entries gave newest-first; chat wants chronological
        return lines
    except Exception as e:  # noqa: BLE001 — diagnostics must never crash finalize
        return [f"(could not fetch Cloud Run logs: {e!r})"]
