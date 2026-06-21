"""Agent OTEL Layer A: config defaults, spawn-path env injection, trace propagation.
Cloud Run + Modal SDKs are mocked; no network, no DSN required."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from infra import store
from infra.schemas import Job, JobKind, JobStatus

# asyncio_mode=auto (pyproject) runs async tests without a marker; the one sync
# test below stays sync, so no module-level pytestmark.


# ---- Task 1: config defaults -------------------------------------------

def test_otel_config_defaults_are_off_and_empty():
    # Re-instantiate Settings so we read declared defaults, not process env.
    from infra.config import Settings
    s = Settings(_env_file=None)
    assert s.agent_otel_enabled is False
    assert s.otel_otlp_endpoint == ""
    assert s.otel_otlp_headers == ""


# ---- Task 2: Cloud Run OTEL env injection ------------------------------

def _fake_jobs(exec_name="projects/p/locations/r/jobs/j/executions/e1"):
    op = MagicMock()
    op.metadata = MagicMock()
    op.metadata.name = exec_name
    jobs = MagicMock()
    jobs.run_job = AsyncMock(return_value=op)
    return jobs


def _captured_env(jobs):
    """Pull the {name: value} env dict from the RunJobRequest passed to run_job."""
    req = jobs.run_job.await_args.args[0]
    env = req.overrides.container_overrides[0].env
    return {e.name: e.value for e in env}


async def test_cloud_run_no_otel_when_disabled(fake_redis):
    from infra.config import settings
    from runner import cloud_run_client
    await store.create_session("s_a", "u", "g", 100)
    jobs = _fake_jobs()
    with patch.object(settings, "agent_otel_enabled", False), \
         patch("runner.cloud_run_client._jobs", lambda: jobs):
        await cloud_run_client.spawn_main_agent_job("s_a", "j_root")
    env = _captured_env(jobs)
    assert "CLAUDE_CODE_ENABLE_TELEMETRY" not in env
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env
    assert "TRACEPARENT" not in env
    assert env["ALPHA_SESSION_ID"] == "s_a"  # existing behavior intact


async def test_cloud_run_injects_otel_when_enabled(fake_redis):
    from infra.config import settings
    from runner import cloud_run_client
    await store.create_session("s_a", "u", "g", 100)
    jobs = _fake_jobs()
    with patch.object(settings, "agent_otel_enabled", True), \
         patch.object(settings, "otel_otlp_endpoint", "https://otlp.example/"), \
         patch.object(settings, "otel_otlp_headers", "sentry-key=pub"), \
         patch("runner.cloud_run_client._jobs", lambda: jobs):
        await cloud_run_client.spawn_main_agent_job(
            "s_a", "j_root", traceparent="00-abc-def-01", baggage="k=v")
    env = _captured_env(jobs)
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == "https://otlp.example/"
    assert env["OTEL_EXPORTER_OTLP_HEADERS"] == "sentry-key=pub"
    assert env["TRACEPARENT"] == "00-abc-def-01"
    assert env["TRACESTATE"] == "k=v"
    ra = env["OTEL_RESOURCE_ATTRIBUTES"]
    assert "alpha.session_id=s_a" in ra
    assert "alpha.job_id=j_root" in ra
    assert "alpha.depth=0" in ra


async def test_cloud_run_enabled_but_no_endpoint_injects_nothing(fake_redis):
    from infra.config import settings
    from runner import cloud_run_client
    await store.create_session("s_a", "u", "g", 100)
    jobs = _fake_jobs()
    with patch.object(settings, "agent_otel_enabled", True), \
         patch.object(settings, "otel_otlp_endpoint", ""), \
         patch("runner.cloud_run_client._jobs", lambda: jobs):
        await cloud_run_client.spawn_main_agent_job("s_a", "j_root")
    assert "CLAUDE_CODE_ENABLE_TELEMETRY" not in _captured_env(jobs)


async def test_cloud_run_omits_empty_traceparent_and_headers(fake_redis):
    from infra.config import settings
    from runner import cloud_run_client
    await store.create_session("s_a", "u", "g", 100)
    jobs = _fake_jobs()
    with patch.object(settings, "agent_otel_enabled", True), \
         patch.object(settings, "otel_otlp_endpoint", "https://otlp.example/"), \
         patch.object(settings, "otel_otlp_headers", ""), \
         patch("runner.cloud_run_client._jobs", lambda: jobs):
        await cloud_run_client.spawn_main_agent_job("s_a", "j_root")  # no traceparent
    env = _captured_env(jobs)
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"  # static still injected
    assert "OTEL_EXPORTER_OTLP_HEADERS" not in env     # empty header omitted
    assert "TRACEPARENT" not in env                    # empty traceparent omitted


# ---- Task 3: Modal sub-agent propagation -------------------------------

async def test_spawn_sub_agent_forwards_trace_context(fake_redis):
    from runner import modal_client
    await store.create_session("s_a", "u_1", "g", 100)
    await store.mint_agent_token("s_a")
    spawn_aio = AsyncMock(return_value=MagicMock(object_id="fc_1"))
    fake_fn = MagicMock(spawn=MagicMock(aio=spawn_aio))
    fake_modal = MagicMock()
    fake_modal.Function.from_name.return_value = fake_fn
    with patch("runner.modal_client._modal", return_value=fake_modal):
        await modal_client.spawn_sub_agent(
            "j_c", "s_a", {"job_id": "j_c"},
            traceparent="00-abc-def-01", baggage="k=v")
    kwargs = spawn_aio.await_args.kwargs
    assert kwargs["traceparent"] == "00-abc-def-01"
    assert kwargs["baggage"] == "k=v"


async def test_spawn_sub_agent_defaults_trace_context_empty(fake_redis):
    from runner import modal_client
    await store.create_session("s_a", "u_1", "g", 100)
    await store.mint_agent_token("s_a")
    spawn_aio = AsyncMock(return_value=MagicMock(object_id="fc_1"))
    fake_fn = MagicMock(spawn=MagicMock(aio=spawn_aio))
    fake_modal = MagicMock()
    fake_modal.Function.from_name.return_value = fake_fn
    with patch("runner.modal_client._modal", return_value=fake_modal):
        await modal_client.spawn_sub_agent("j_c", "s_a", {"job_id": "j_c"})
    kwargs = spawn_aio.await_args.kwargs
    assert kwargs["traceparent"] == ""
    assert kwargs["baggage"] == ""


# ---- Task 4: runner loop trace-context extraction ----------------------

async def test_session_loop_passes_trace_context_to_spawn(fake_redis):
    from runner import loops
    await store.create_session("s_a", "u_1", "explore", 100)
    await store.create_job(Job(id="j_root", session_id="s_a", depth=0,
                               kind=JobKind.agent, status=JobStatus.queued, backend="modal"))
    await store.get_redis().json().set("session:s_a", "$.root_job_id", "j_root")
    await store.enqueue_session("s_a")
    spawn = AsyncMock(return_value="exec_1")
    with patch("runner.loops.spawn_main_agent_job", spawn), \
         patch("runner.loops.sentry_sdk.get_traceparent", return_value="00-t-p-01"), \
         patch("runner.loops.sentry_sdk.get_baggage", return_value="b=1"):
        await loops._consume_sessions_once()
    assert spawn.await_args.kwargs["traceparent"] == "00-t-p-01"
    assert spawn.await_args.kwargs["baggage"] == "b=1"


async def test_dispatch_loop_passes_trace_context_to_spawn(fake_redis):
    from runner import loops
    await store.create_session("s_a", "u_1", "explore", 100)
    await store.create_job(Job(id="j_c", session_id="s_a", parent_job_id="j_root",
                               depth=1, kind=JobKind.agent, status=JobStatus.queued,
                               backend="modal"))
    await store.enqueue_dispatch("j_c")
    spawn = AsyncMock(return_value="fc_1")
    with patch("runner.loops.spawn_sub_agent", spawn), \
         patch("runner.loops.sentry_sdk.get_traceparent", return_value="00-t-p-01"), \
         patch("runner.loops.sentry_sdk.get_baggage", return_value="b=1"):
        await loops._consume_dispatches_once()
    assert spawn.await_args.kwargs["traceparent"] == "00-t-p-01"
    assert spawn.await_args.kwargs["baggage"] == "b=1"


async def test_default_path_injects_no_otel_env_end_to_end(fake_redis):
    """The guarantee that matters: on the default path (no DSN, agent_otel_enabled
    false) the real session loop -> real spawn_main_agent_job produces a Cloud Run
    request with NO OTEL/TRACEPARENT env vars — even though Sentry still hands the loop
    a generated traceparent (start_transaction creates a span object regardless of DSN).
    The injection gate in cloud_run_client, not an empty traceparent, is what protects us."""
    from infra.config import settings
    from runner import loops
    await store.create_session("s_a", "u_1", "explore", 100)
    await store.create_job(Job(id="j_root", session_id="s_a", depth=0,
                               kind=JobKind.agent, status=JobStatus.queued, backend="modal"))
    await store.get_redis().json().set("session:s_a", "$.root_job_id", "j_root")
    await store.enqueue_session("s_a")
    jobs = _fake_jobs()
    with patch.object(settings, "agent_otel_enabled", False), \
         patch("runner.cloud_run_client._jobs", lambda: jobs):
        await loops._consume_sessions_once()  # real spawn_main_agent_job, real sentry (no DSN)
    env = _captured_env(jobs)
    assert "CLAUDE_CODE_ENABLE_TELEMETRY" not in env
    assert "OTEL_EXPORTER_OTLP_ENDPOINT" not in env
    assert "TRACEPARENT" not in env
    assert env["ALPHA_SESSION_ID"] == "s_a"  # the agent still spawns normally
