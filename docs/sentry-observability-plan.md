# Sentry AI Trace Observability Plan

Status: finalized plan for Phase 1 testing visibility. This is an internal-first
observability layer for the prize demo; it does not replace Redis/SSE as the
product-visible source of truth.

References reviewed:

- Python SDK: https://docs.sentry.io/platforms/python/
- FastAPI integration: https://docs.sentry.io/platforms/python/integrations/fastapi/
- Python logs: https://docs.sentry.io/platforms/python/logs/
- Python tracing: https://docs.sentry.io/platforms/python/tracing/
- Next.js SDK: https://docs.sentry.io/platforms/javascript/guides/nextjs/
- LangChain AI monitoring: https://docs.sentry.io/platforms/python/integrations/langchain/
- MCP monitoring: https://docs.sentry.io/platforms/python/integrations/mcp/

## Goal

Use Sentry as the operator/demo view for agent traces, tool calls, dispatches,
runtime failures, and cloud handoffs while AlphaResearch enters Phase 1 testing.
The demo narrative should be inspectable in Sentry even when the AlphaResearch UI
only shows the product stream.

Redis remains authoritative for sessions, jobs, runs, artifacts, transcript,
and SSE events. Sentry correlates to that state with stable tags and attributes:

- `alpha.session_id`
- `alpha.job_id`
- `alpha.parent_job_id`
- `alpha.depth`
- `alpha.job_kind`
- `alpha.event_type`
- `alpha.dispatch_backend`
- `ai.model`
- `ai.tool.name`

## Current Architecture To Instrument

The current backend is the PR #8 architecture:

- FastAPI API plus `runner/` loops run in one Cloud Run service.
- The main agent runs as a Cloud Run Job, one execution per session.
- Sub-agents run as Modal Functions, one per dispatched idea.
- Agents push events, transcript, dispatches, and child-status requests through
  the hidden `/internal/*` API using a per-session token.
- Redis is the state/event/queue source of truth.
- GCS stores artifacts.
- The runner reconciles Cloud Run and Modal lifecycle state.

This means Sentry should be initialized in every process boundary, not only the
API:

| Runtime | Entrypoint | Purpose |
|---|---|---|
| API + runner | `orchestrator/api.py` | HTTP requests, SSE, internal API, runner loops |
| Main agent | Cloud Run Job image entrypoint | Claude Code session, planning, dispatching |
| Sub-agent | `infra/modal_app.py::sub_agent` | Assigned idea execution, result/artifact write |
| Modal experiment | `infra/modal_app.py::run_job` | Prebaked experiment path |
| Local smoke/scripts | `scripts/*.py` where they boot agent paths | Sentry-disabled smoke and local repro |
| Next.js | `web/` | Frontend errors only; no UI trace work in this pass |

## Implementation Scope

### Dependencies And Config

Add Python dependency:

- `sentry-sdk[fastapi]>=2.35`

Add web dependency:

- `@sentry/nextjs`

Add environment variables to `.env.example` and cloud secret runbooks:

```bash
SENTRY_DSN=
SENTRY_ENVIRONMENT=development
SENTRY_RELEASE=
SENTRY_TRACES_SAMPLE_RATE=1.0
SENTRY_PROFILES_SAMPLE_RATE=0.0
ALPHA_SENTRY_CAPTURE_CONTENT=true

NEXT_PUBLIC_SENTRY_DSN=
SENTRY_AUTH_TOKEN=
SENTRY_ORG=
SENTRY_PROJECT=
```

For Modal, `alpha-secrets` should carry `SENTRY_DSN`, `SENTRY_ENVIRONMENT`,
`SENTRY_RELEASE`, sample rates, and `ALPHA_SENTRY_CAPTURE_CONTENT` when remote
jobs should emit traces.

### Observability Module

Add `infra/observability.py` with:

- `init_observability(service_name: str) -> None`
- `scrub(obj) -> Any`
- helpers to set AlphaResearch tags/attributes on the current Sentry scope/span
- helpers to create scrubbed spans for tool calls, dispatches, store events, and
  agent runs

`init_observability()` must no-op when `SENTRY_DSN` is unset. Sentry-disabled mode
is a required local/dev path.

Use SDK configuration:

- `enable_logs=True`
- `traces_sample_rate` from `SENTRY_TRACES_SAMPLE_RATE`
- `profiles_sample_rate` from `SENTRY_PROFILES_SAMPLE_RATE`
- `environment` from `SENTRY_ENVIRONMENT`
- `release` from `SENTRY_RELEASE`
- `send_default_pii=False`
- `before_send`, `before_send_transaction`, and log/event scrubbing hooks

The scrubber must recursively redact secret-like keys and bound payload size:

- secret keys: `api_key`, `apikey`, `token`, `password`, `passwd`,
  `authorization`, `cookie`, `secret`, `credential`, `auth_`, `_auth`,
  `private_key`, `access_key`, `client_secret`
- max string length: 2,000 characters
- max collection items: 50
- max recursion depth: 8

### Span Model

Use custom spans around AlphaResearch-owned boundaries. Do not depend on automatic
AI integrations recognizing Claude Code or `claude-agent-sdk`.

Top-level transactions:

- `alpha.session.create` around `POST /sessions`
- `ai.agent.run` around main-agent and sub-agent execution
- `alpha.runner.loop` around each runner loop iteration where work happens
- `alpha.modal.function` around Modal `run_job` and `sub_agent`

Child spans:

- `alpha.runner.spawn_main_agent`
- `alpha.runner.spawn_sub_agent`
- `alpha.runner.poll_cloud_run`
- `alpha.runner.poll_modal`
- `alpha.runner.reconcile`
- `alpha.internal.dispatch`
- `alpha.internal.children`
- `alpha.store.emit_event`
- `alpha.store.write_run`
- `alpha.store.put_artifact`
- `ai.tool.dispatch_subagent`
- `ai.tool.check_children`
- `ai.tool.read_artifacts`
- `ai.tool.finalize`
- `ai.claude_code.session`

Logs and breadcrumbs:

- session created
- main-agent spawned
- dispatch accepted/rejected
- sub-agent spawned
- child result finalized
- artifact uploaded
- token/auth failures, scrubbed
- volume bridge waits/failures
- cloud poll failures

### Phase 1 Instrumentation Map

This is the concrete map for the first implementation pass. It favors the
operator questions needed during cloud bring-up over exhaustive service
documentation.

| Sentry operation | Kind | File/function | Purpose | Key tags |
|---|---|---|---|---|
| automatic request transaction | transaction | `orchestrator/api.py` via `FastApiIntegration` | `/sessions` and `/internal/*` request traces | `route`, `status` |
| `alpha.runner.spawn_main_agent` | transaction | `runner/loops.py::_consume_sessions_once` | main-agent Cloud Run Job launch | `session_id`, `job_id` |
| `alpha.runner.spawn_sub_agent` | transaction | `runner/loops.py::_consume_dispatches_once` | sub-agent Modal spawn | `session_id`, `job_id`, `depth` |
| `alpha.runner.reconcile` | transaction | `runner/loops.py::_reconcile_once` per transition | finalize a done/failed job | `session_id`, `job_id`, `depth`, `backend`, `poll_state` |
| `alpha.modal.reload_volume` | span | `runner/loops.py::_finalize_done` | Modal Volume bridge | `alpha.sentinel_present` |
| `alpha.gcs.upload_artifacts` | span | `runner/loops.py::_finalize_done` | artifact ship to GCS | `artifact_count` |
| `alpha.internal.dispatch` | span | `runner/internal_api.py::post_dispatch` | agent-driven child dispatch and guardrail result | `session_id`, `parent_job_id`, `depth`, `dispatch_result` |
| `alpha.event` | breadcrumb | `infra/store.py::emit_event` | scrubbed event timeline | none |
| `init` | process init | `orchestrator/api.py`, `infra/modal_app.py::run_job`, `scripts/*.py` | process Sentry init | `service_name` |

### Content Capture Policy

Initial policy: full but scrubbed.

Allowed after scrub/limits:

- prompts and goals
- agent messages
- tool names
- tool inputs/results
- dispatch plans and idea metadata
- result summaries and metrics
- artifact names/URLs
- structured error context

Never allow:

- bearer tokens
- API keys
- raw service-account JSON
- cookies
- authorization headers
- Redis URLs with passwords
- unbounded tool output
- unbounded transcript payloads

When `ALPHA_SENTRY_CAPTURE_CONTENT=false`, keep tags, attributes, tool names,
statuses, timings, and counts, but drop prompt/message/tool body content.

## Integration Points

### Current, Phase 1

These are the highest-value integration points before live cloud testing:

1. API startup and request traces in `orchestrator/api.py`.
2. Internal API spans in `runner/internal_api.py`.
3. Runner lifecycle spans in `runner/loops.py`.
4. Cloud Run client spans in `runner/cloud_run_client.py`.
5. Modal client spans in `runner/modal_client.py`.
6. Artifact spans in `runner/gcs_uploader.py` and `infra/store.py`.
7. Agent hook telemetry in `agent/*/.claude/hooks/*`.
8. Modal app initialization in `infra/modal_app.py`.
9. Next.js error capture in `web/`, with no feature/UI changes.

The first manual demo should answer:

- Did the API receive the session?
- Did the runner acquire leadership?
- Did the main-agent Cloud Run Job spawn?
- Did the main agent dispatch children?
- Did Modal spawn the sub-agent?
- Did the runner see or fail to see the sub-agent result?
- Was the failure the known Modal Volume bridge?
- Which `session_id` / `job_id` maps this trace back to Redis?

### Future

After Phase 1 cloud bring-up, add:

- Cloud Run deployment/revision tags and release health.
- Modal cold-start/build timing spans.
- Real RL training spans per seed/eval/checkpoint.
- Sentry metrics for job counts, fanout, depth, budget burn, artifact count, and
  success/failure rates.
- Sentry cron/check-in style monitoring for long runner loops if they move to a
  scheduled or worker-only runtime.
- Frontend trace propagation from session creation to backend request, if the web
  demo becomes user-facing again.
- Automatic AI integration experiments if the runtime later moves to a supported
  framework such as LangChain.
- OpenTelemetry bridge only if direct SDK spans become too limiting.
- Break down each Phase 1 instrumentation-map entry into detailed operator docs
  once the cloud path is live; this is intentionally not part of the first
  implementation pass.

## Phase 1 Task Plan

1. Land `infra/observability.py` and scrubber tests.
2. Add Python/web dependencies and Sentry env template values.
3. Initialize Sentry in API, Modal app, main-agent image entrypoint, sub-agent
   path, and local smoke scripts.
4. Add tags/attributes and spans to runner, internal API, Cloud Run client, Modal
   client, store event/artifact writes, and agent hooks.
5. Add Next.js Sentry config with DSN-unset local behavior.
6. Run the existing test suite with Sentry unset.
7. Run `scripts/smoke_infra.py` with Sentry unset.
8. Run one manual DSN-enabled session and verify trace grouping in Sentry.
9. Update the cloud runbook with Sentry secret propagation for GCP and Modal.

## Test Plan

Automated:

- scrubber redacts secret-like keys at any depth
- scrubber truncates long strings and large collections
- scrubber preserves normal session/job/tool metadata
- importing API and Modal app with no `SENTRY_DSN` performs no network calls
- existing backend tests pass with Sentry unset
- Next.js builds with `NEXT_PUBLIC_SENTRY_DSN` unset

Manual:

- set DSN locally
- start API
- create one session
- trigger at least one dispatch path
- confirm Sentry shows one trace with API, runner, internal dispatch, spawn, poll,
  reconcile, and agent/tool spans
- confirm event/log payloads are scrubbed and bounded
- confirm Redis/SSE still has the authoritative event stream

## Explicit Non-Goals

- No REST API changes.
- No Redis schema changes.
- No SSE schema changes.
- No frontend type changes.
- No in-app trace UI.
- No Sentry dependency on secrets being present in local dev.

## Known Repo Drift To Resolve While Implementing

- `README.md` still describes the older Modal-main-agent status.
- `scripts/deploy_cloudrun.sh` references `deploy/main-agent.Dockerfile`, but that
  file is missing in the current tree.
- A previous observability stash exists and can seed this work, but it touches
  deleted `orchestrator/worker.py` and should be applied selectively.
