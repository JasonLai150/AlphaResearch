# Agent-Level Sentry Observability — Prerequisites

> Status: **research / design only**. No code changed by this document.
> Scope: instrumenting the *agent* processes (the "blackboxes") — the Claude Code
> CLI loops that run as a Cloud Run **Job** (main-agent) and Modal **Functions**
> (sub-agents). The orchestration tier (API, runner loops, store) is handled
> separately by `docs/sentry-observability-plan.md` /
> `/home/eahtr/.claude/plans/sentry-ai-trace-atomic-russell.md`.

---

## 0. Verified current state (read, not assumed)

| Fact | Evidence |
|---|---|
| main-agent = Cloud Run **Job**, Node Claude Code CLI as entrypoint | `deploy/main-agent.Dockerfile:44,60` (`npm install -g @anthropic-ai/claude-code`, `ENTRYPOINT ["claude", "--dangerously-skip-permissions"]`) |
| sub-agent = Modal **Function**, same Node CLI entrypoint | `infra/modal_app.py:84-105` (`sub_agent`, `subprocess.run(["claude", ...])`); image from `deploy/sub-agent.Dockerfile:56,77` |
| Agent images deliberately exclude `infra/`, `runner/`, `orchestrator/` | Comments in `deploy/main-agent.Dockerfile:15-18`, `deploy/sub-agent.Dockerfile:20-23` |
| Only owned Python in the agent process context = the hooks | `agent/main-agent/.claude/hooks/*.py`, `agent/sub-agent/.claude/hooks/*.py` |
| Hooks are **stdlib-only by design**; `_push.py` forbids importing infra | `agent/main-agent/.claude/hooks/_push.py:4-7` (docstring), uses only `json/os/sys/time/urllib` |
| Hooks already POST telemetry to runner `/internal/*` over HTTP | `_push.py:push()` → `/internal/events`, `/internal/transcript`; endpoints in `runner/internal_api.py:92,102,111` |
| Hooks registered per tool event | `agent/main-agent/.claude/settings.json` (PreToolUse/PostToolUse/UserPromptSubmit/Stop), `agent/sub-agent/.claude/settings.json` (PostToolUse/Stop) |
| Per-execution env injected at spawn | main: `runner/cloud_run_client.py:48-62` (container overrides: `ALPHA_SESSION_ID/JOB_ID/DEPTH/INTERNAL_TOKEN/INTERNAL_RUNNER_URL`); sub: `runner/modal_client.py:82-99` + `infra/modal_app.py:93-102` |
| Secrets: Modal `alpha-secrets` for sub-agents; GCP Secret Manager → Cloud Run for main-agent | `scripts/deploy_modal.sh:21-26`; `scripts/deploy_cloudrun.sh:67-92`; `scripts/gcp_bootstrap.sh` (secrets `anthropic-api-key`, `alpha-redis-url`, `gcs-sa-key`) |
| Orchestration `infra/observability.py` already exists (init/scrub/tag_alpha) | `infra/observability.py` present on disk |
| Runner spawn **transactions are NOT yet wired** in `runner/loops.py` | `grep start_transaction runner/loops.py` → none; spawns are bare at `loops.py:122,145`. The Sentry plan's Task 3 is not yet executed. **This matters: the designated parent transactions don't exist yet.** |

Net: agents are currently observable only indirectly — their hooks push
event/transcript/summary records into Redis via the runner API. There is **no
LLM-turn data** (tokens, model, cost, per-turn latency) and **no trace linkage**
between a runner spawn and the agent it spawned.

---

## 1. Layers where agent visibility can be captured

There are three distinct layers, each with different ownership and different
realistic instrumentation paths.

### Layer A — The Claude Code CLI loop (LLM turns, tokens, model, cost, tool spans)

We do **not** own the CLI source (it's the published Node binary). The only
realistic way to get LLM-level data is **Claude Code's native OpenTelemetry
export**, which Sentry can ingest via its OTLP endpoint.

Native telemetry facts (verified via claude-code-guide / Anthropic docs, current
as of 2026-06):

- Enable with `CLAUDE_CODE_ENABLE_TELEMETRY=1`. Traces are gated behind
  `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1`.
- Exporters configured by standard OTEL env vars: `OTEL_TRACES_EXPORTER=otlp`,
  `OTEL_LOGS_EXPORTER=otlp`, `OTEL_METRICS_EXPORTER` (do **not** point metrics at
  Sentry — see below), `OTEL_EXPORTER_OTLP_PROTOCOL` (use `http/protobuf` for
  Sentry), `OTEL_EXPORTER_OTLP_*_ENDPOINT`, `OTEL_EXPORTER_OTLP_HEADERS`.
- Three signal types are emitted:
  - **Metrics**: `claude_code.token.usage` (input/output/cacheRead/cacheCreation,
    `model`), `claude_code.cost.usage`, `claude_code.session.count`,
    `claude_code.code_edit_tool.decision`, etc.
  - **Logs/events**: `claude_code.api_request` (model, duration_ms, token counts,
    request_id), `claude_code.tool_result`, `claude_code.tool_decision`,
    `claude_code.user_prompt`, `claude_code.api_error`, etc.
  - **Traces/spans** (beta): `claude_code.interaction` (one prompt→response),
    `claude_code.llm_request` (one API call; model, ttft_ms, tokens, stop_reason),
    `claude_code.tool`, `claude_code.hook`.
- Content gating: `OTEL_LOG_USER_PROMPTS=1`, `OTEL_LOG_TOOL_DETAILS=1`,
  `OTEL_LOG_TOOL_CONTENT=1`, `OTEL_LOG_RAW_API_BODIES`. **All default off** — this
  is where our content policy / scrubbing lever lives for Layer A (see §4).
- Cardinality: `OTEL_METRICS_INCLUDE_SESSION_ID` (default true) puts the CLI's own
  `session.id` on metrics — note this is the **Claude Code session id, not our
  `alpha.session_id`**. We must inject our IDs via `OTEL_RESOURCE_ATTRIBUTES`.
- Export intervals: `OTEL_METRIC_EXPORT_INTERVAL` (60s), `OTEL_LOGS_EXPORT_INTERVAL`
  (5s), `OTEL_TRACES_EXPORT_INTERVAL` (5s).

**Sentry OTLP ingest (verified):** Sentry accepts **traces and logs** over OTLP,
**not metrics** (open beta). Endpoint shape:
`https://o<org>.ingest.sentry.io/api/<project>/integration/otlp/v1/{traces,logs}`,
auth header `x-sentry-auth: sentry sentry_key=<public-key>`.

**Implication for Layer A:** the realistic path is
**Claude Code OTEL traces+logs → Sentry OTLP endpoint**. Token/cost **metrics**
are emitted by the CLI but Sentry won't ingest them as metrics — they would need
a separate TSDB (Prometheus/Grafana/Datadog) OR we accept them only via the
`claude_code.llm_request`/`api_request` span/log attributes (which carry the same
token counts) and skip the metrics signal for Sentry.

### Layer B — The hooks (tool-level spans, our owned Python)

The hooks are the only owned code inside the agent process. They are short-lived
subprocesses (one per tool event), stdlib-only, and must never raise. Making a
hook emit a *manual Sentry span* requires:

1. `sentry-sdk` present in **both** agent images (`deploy/main-agent.Dockerfile`,
   `deploy/sub-agent.Dockerfile`) — currently neither carries it.
2. A tiny `sentry_sdk.init(...)` + scrubber callable for the hook to import. This
   conflicts with the stdlib-only rule (`_push.py:4-7`) — see decision §4.2.
3. **Synchronous flush before exit** (`sentry_sdk.flush(timeout=...)`): the hook
   process dies immediately, so the default background transport never sends.
   This adds network latency *inline in the agent loop* on every tool event.
4. A latency budget: `_push.py` already caps itself (2 attempts, 0.25s backoff,
   1s timeout). A Sentry flush per PostToolUse on every tool call is heavier; it
   must be bounded the same way or it slows every agent turn.

Key limitation (verified): **Claude Code does NOT propagate W3C trace context to
hook subprocesses.** There is no `TRACEPARENT` env handed to hooks. So a hook
span cannot natively nest under the CLI's own `claude_code.tool` span. A hook span
can only be correlated by *tag* (`alpha.session_id`, `alpha.job_id`) or made to
nest under the **runner's** spawn trace if we propagate that trace via env (§3).

Given native `claude_code.tool` spans already exist in Layer A, **manual hook
spans are largely redundant for tool timing** and are mainly valuable for the two
things the hooks do that the CLI doesn't: dispatch-record validation outcomes
(`validate_dispatch.py`), web-fetch capping (`cap_web_fetch.py`), and the
result/sentinel finalize path (`finalize.py`). Recommendation in §6.

### Layer C — The Python wrappers (`sub_agent()`) and the experiment path

- `infra/modal_app.py:run_job` (experiment path) runs in the `image` that DOES
  carry `infra` (`add_local_python_source("agent","infra")`, `modal_app.py:41`).
  The Sentry plan already designates this for `init_observability("modal-experiment")`.
  This is **not** an agent blackbox — it's already instrumentable.
- `infra/modal_app.py:sub_agent` runs in `sub_image` (built from
  `deploy/sub-agent.Dockerfile`) which has **no `infra`**. It is a thin Python
  shim that sets env and `subprocess.run`s the CLI, then commits the volume. It
  could host a *parent* span around the CLI subprocess **only if** `sentry-sdk` is
  added to `sub_image` AND a no-infra init is available there. It is the natural
  place to call `continue_trace()` for sub-agents (§3).
- The main-agent has **no equivalent Python wrapper** — Cloud Run launches the
  CLI directly as the container ENTRYPOINT. There is nothing to wrap. Main-agent
  Layer-C instrumentation would require either an entrypoint shim script or
  relying entirely on Layer A (OTEL) + Layer B (hooks).

---

## 2. Summary: what each layer can deliver

| Want | Layer | Mechanism | Owns source? | Sentry-ingestible? |
|---|---|---|---|---|
| LLM turns / tokens / model / cost / per-turn latency | A | CLAUDE_CODE OTEL traces+logs → Sentry OTLP | no | traces+logs yes; metrics no |
| Tool spans (timing) | A | native `claude_code.tool` span | no | yes (traces) |
| Dispatch/guardrail/finalize outcomes | B | manual `sentry_sdk` span in hook | yes | yes |
| Sub-agent process wrapper / trace root | C | `sub_agent()` continue_trace + span | yes (shim) | yes |
| Main-agent process wrapper | C | none (CLI is the entrypoint) | n/a | via A+B only |

---

## 3. HARD BLOCKERS — must exist before agent Sentry can be built

### Blocker 1 — `sentry-sdk` is not in the agent images
Neither `deploy/main-agent.Dockerfile` nor `deploy/sub-agent.Dockerfile` installs
`sentry-sdk`. Layer B and Layer C are impossible until it is added. (Layer A
needs no SDK in the image — it's native CLI OTEL, no Python.) This intentionally
violates the "stdlib-only hooks" rule and the "lean image" intent, so it is a
decision as well as a blocker (§4.2).

### Blocker 2 — No trace-context propagation to the agent (the big one)
Today **each runner action is its own root transaction** because no trace id flows
to the agent. To make agent spans nest under the runner's spawn transaction:

1. The runner must **start the spawn transaction first** and then **inject the
   propagation headers as env vars** into the spawned container:
   - `sentry-trace` (the `sentry_sdk` `trace_propagation_headers` / W3C
     `traceparent`) and `baggage` (carries head-based sampling decision + DSC).
   - Functions to change:
     - main-agent: `runner/cloud_run_client.py:spawn_main_agent_job` — add two
       `run_v2.EnvVar` entries (e.g. `SENTRY_TRACE`, `SENTRY_BAGGAGE`) in the
       `container_overrides` env list (alongside the existing `ALPHA_*` vars at
       `cloud_run_client.py:48-62`).
     - sub-agent: `runner/modal_client.py:spawn_sub_agent` passes them as
       function kwargs (like `internal_token`); `infra/modal_app.py:sub_agent`
       copies them into `env` before `subprocess.run` (around `modal_app.py:93-102`).
   - The headers come from `sentry_sdk.get_traceparent()` /
     `sentry_sdk.get_baggage()` **inside the runner spawn transaction**, so the
     transaction must wrap the spawn call (this is exactly the
     `alpha.runner.spawn_main_agent` / `alpha.runner.spawn_sub_agent` transactions
     that the orchestration plan's Task 3 defines but **has not yet wired** —
     `runner/loops.py:122,145` are still bare). **Prerequisite ordering: the
     runner spawn transactions must land before agent propagation can be built.**

2. The agent side must **continue** the trace:
   - For manual hook/wrapper spans (Layer B/C): call
     `sentry_sdk.continue_trace({"sentry-trace": os.environ["SENTRY_TRACE"],
     "baggage": os.environ["SENTRY_BAGGAGE"]})` then start the transaction inside
     it. Natural home: `infra/modal_app.py:sub_agent` (sub) and, for main-agent,
     a tiny entrypoint shim or each hook reading the env.
   - For native CLI OTEL (Layer A): Claude Code consumes the standard
     `TRACEPARENT` env on its own process for *outgoing* spans **only if** it
     honors W3C parent context env (needs verification — the CLI sets TRACEPARENT
     for child Bash, but ingesting an inbound parent is not documented). If it
     does not, Layer A spans will be a **separate trace** correlated only by tag
     (`alpha.session_id`) — acceptable but not nested. This is an open verification
     item, not a build blocker for Layer B/C.

3. **Head-based sampling via baggage:** the sampling decision is made once in the
   runner (head) and carried in `baggage`; the agent side must NOT re-sample
   independently or the trace tears. `continue_trace` honors the inbound decision
   automatically when baggage is present.

### Blocker 3 — Synchronous flush / latency budget is undecided
Hook subprocesses and the `sub_agent` shim exit immediately; Sentry's async
transport won't deliver without an explicit `sentry_sdk.flush(timeout=N)`. A flush
on every PostToolUse adds inline network latency to every agent turn. A budget
(timeout, sample rate, or "spans only on interesting events") must be fixed before
building Layer B (§4.3).

### Blocker 4 — ID/tag mapping for Layer A
Claude Code's native telemetry tags everything with its **own** `session.id`, not
our `alpha.session_id`/`alpha.job_id`. Without injecting our IDs via
`OTEL_RESOURCE_ATTRIBUTES` (e.g.
`alpha.session_id=<sid>,alpha.job_id=<jid>,alpha.depth=<d>`) at spawn time, Layer A
data cannot be correlated back to Redis or to the runner transactions. The same
spawn-time env-injection sites as Blocker 2 must also set this.

### Blocker 5 — Secret/config propagation does not carry any Sentry vars yet
`scripts/deploy_modal.sh` (alpha-secrets) and `scripts/deploy_cloudrun.sh` /
`scripts/gcp_bootstrap.sh` (GCP secrets + Cloud Run env) inject **zero** Sentry
config. The DSN, environment, release, sample rates, and OTLP endpoint/headers all
need to be added to those mechanisms before any agent-side Sentry runs (§5).

---

## 4. Design decisions to LOCK before building

### 4.1 OTEL-native (Layer A) vs manual hook spans (Layer B) vs both
- **Recommended:** Layer A (native OTEL traces+logs → Sentry OTLP) is the only way
  to get LLM-turn data and is *zero owned code* — just env vars. Make it Phase 1.
- Layer B manual spans are **mostly redundant** with native `claude_code.tool`
  spans; reserve them for our owned semantics (dispatch validation result,
  web-cap, finalize/sentinel). Decide whether that marginal value justifies
  putting `sentry-sdk` + flush latency into the hot path.
- Fork to lock: **"both" only if** the hook-specific tags (dispatch_result,
  sentinel_present at the agent edge) are deemed worth the image weight + latency.

### 4.2 How to share the scrubber/init with stdlib-only hooks
`infra/observability.py` cannot be imported by hooks (no `infra` in the image, and
`_push.py:4-7` forbids it). Two forks:
- **(a) Vendor a copy:** ship a tiny stdlib+sentry obs module *inside* the agent
  workspace (e.g. `agent/main-agent/.claude/hooks/_obs.py` and the sub-agent twin)
  that duplicates `scrub()` + a minimal `init`. Keeps the no-infra rule intact;
  cost = a second source of truth for the scrubber (must be kept in sync, ideally
  by a copy step in the Dockerfile or a generated-file check).
- **(b) Relax the rule** for one tiny obs-only module placed where the image can
  see it. Simpler but breaks the deliberate isolation invariant.
- **Recommended:** (a) with a sync-check test, since the scrubber correctness is a
  security property (token redaction) and we don't want drift, but we also don't
  want to weaken the import firewall.

### 4.3 Sampling + flush/latency budget
- Lock `SENTRY_TRACES_SAMPLE_RATE` for agents (likely lower than the runner's 1.0;
  agents are high-volume). Head-based decision flows from the runner via baggage
  (§3), so the agent should **inherit**, not re-sample.
- Lock a hook flush timeout (e.g. ≤0.5s) and whether hooks flush at all vs only
  the Stop hook. For Layer A, lock the OTEL export interval and whether to flush
  on CLI exit.

### 4.4 Release/version tagging across images
Three images (api, main-agent, sub-agent) are built/tagged independently
(`deploy_cloudrun.sh` uses `TAG=v$(date ...)`; Modal builds `sub_image` from the
Dockerfile). Lock how `SENTRY_RELEASE` is set per image so a Sentry release
correlates the right code across the orchestration + both agent images. Likely:
pass the git SHA / build tag as a build-arg or env in each deploy script.

### 4.5 (verify) Does Claude Code honor an inbound W3C parent for its OTEL spans?
Open item (Blocker 2.2). If yes → Layer A nests under the runner trace for free.
If no → Layer A is a sibling trace correlated by `alpha.*` resource attributes
only. Decide whether tag-correlation is sufficient for Phase 1 (it is).

---

## 5. Config / secret propagation — exactly what changes where

Variables needed agent-side:

| Var | Layer | Purpose |
|---|---|---|
| `SENTRY_DSN` | B/C | manual SDK init (hooks / sub_agent wrapper) |
| `SENTRY_ENVIRONMENT` | B/C | env tag |
| `SENTRY_RELEASE` | A/B/C | release correlation across images (§4.4) |
| `SENTRY_TRACES_SAMPLE_RATE` | B/C | agent sampling (inherits from baggage when propagated) |
| `ALPHA_SENTRY_CAPTURE_CONTENT` | B/C | content on/off lever for manual spans |
| `CLAUDE_CODE_ENABLE_TELEMETRY=1` | A | enable native OTEL |
| `CLAUDE_CODE_ENHANCED_TELEMETRY_BETA=1` | A | enable native traces |
| `OTEL_TRACES_EXPORTER=otlp`, `OTEL_LOGS_EXPORTER=otlp` | A | exporters |
| `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` | A | Sentry needs HTTP/protobuf |
| `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`, `OTEL_EXPORTER_OTLP_LOGS_ENDPOINT` | A | Sentry OTLP URLs |
| `OTEL_EXPORTER_OTLP_HEADERS` (`x-sentry-auth: sentry sentry_key=<key>`) | A | Sentry OTLP auth |
| `OTEL_LOG_USER_PROMPTS`, `OTEL_LOG_TOOL_DETAILS`, `OTEL_LOG_TOOL_CONTENT` | A | content gating (default off; tie to content policy) |
| `OTEL_RESOURCE_ATTRIBUTES=alpha.session_id=…,alpha.job_id=…,alpha.depth=…` | A | correlate native data to Redis/runner (Blocker 4) |
| `SENTRY_TRACE`, `SENTRY_BAGGAGE` (per-execution) | B/C | trace propagation (Blocker 2) |

Where each lands:

- **Static, same for every run (DSN, environment, release, OTEL exporter/endpoint/
  headers/enable flags, sample rate, content flags):**
  - sub-agent: add to **Modal `alpha-secrets`** in `scripts/deploy_modal.sh:21-26`
    (and they appear in `sub_agent`'s `os.environ` automatically since
    `infra/modal_app.py:50,84` attach the secret).
  - main-agent: add as **Cloud Run Job env/secrets** in
    `scripts/deploy_cloudrun.sh:87-92` (`--set-secrets` for `SENTRY_DSN`/OTLP key
    via Secret Manager, `--set-env-vars` for the non-secret OTEL flags). Create the
    `sentry-dsn` (and OTLP key) secret in `scripts/gcp_bootstrap.sh` alongside the
    existing `anthropic-api-key`/`alpha-redis-url`.
- **Per-execution (the propagation + ID-mapping vars: `SENTRY_TRACE`,
  `SENTRY_BAGGAGE`, `OTEL_RESOURCE_ATTRIBUTES`):**
  - main-agent: `runner/cloud_run_client.py:spawn_main_agent_job`
    container-overrides env list (`cloud_run_client.py:48-62`).
  - sub-agent: `runner/modal_client.py:spawn_sub_agent` kwargs →
    `infra/modal_app.py:sub_agent` env copy (`modal_app.py:93-102`).

Files that change for config: `scripts/deploy_modal.sh`,
`scripts/deploy_cloudrun.sh`, `scripts/gcp_bootstrap.sh`, `.env.example`,
`runner/cloud_run_client.py`, `runner/modal_client.py`, `infra/modal_app.py`, and
(for OTLP secret) the GCP/Modal secret stores. Layer B/C also add `sentry-sdk` to
`deploy/main-agent.Dockerfile` and `deploy/sub-agent.Dockerfile`.

---

## 6. Recommended phased build order

**Phase 0 — Prerequisite: land the runner spawn transactions (orchestration plan
Task 3).** They are not yet in `runner/loops.py` (`:122,145` are bare). These are
the **designated parents** for any propagated agent trace; nothing agent-side can
nest without them. Ensure that plan does not remove or rename
`alpha.runner.spawn_main_agent` / `alpha.runner.spawn_sub_agent` — they are the
attach points.

**Phase 1 — Layer A, native OTEL → Sentry OTLP (lowest effort, highest LLM
value).** No image changes, no owned code. Add the `CLAUDE_CODE_*` + `OTEL_*` env
(static via secrets, plus `OTEL_RESOURCE_ATTRIBUTES` per-execution for our IDs).
Verify whether the CLI nests under an inbound `TRACEPARENT`; if not, accept
tag-correlation. Gives tokens/model/cost/turn-latency/tool-timing immediately.

**Phase 2 — Trace propagation plumbing (Blocker 2).** Inject `SENTRY_TRACE` /
`SENTRY_BAGGAGE` from the runner spawn transactions into both spawn sites. Even
before any manual agent span, this lets a future agent span (and possibly Layer A,
pending §4.5) join one trace; head-based sampling via baggage.

**Phase 3 — Layer C wrapper span for sub-agents.** Add `sentry-sdk` to
`sub-agent.Dockerfile`, a no-infra init in `sub_image`, and wrap the
`subprocess.run` in `infra/modal_app.py:sub_agent` with `continue_trace` + a
transaction tagged `alpha.*`. Synchronous flush after the subprocess returns
(latency is fine here — it's once per sub-agent, not per turn).

**Phase 4 — Layer B manual hook spans (optional, only the owned-semantics ones).**
Vendor `_obs.py` into the hook dirs (§4.2a), add `sentry-sdk` to both images, emit
spans only where the CLI's native data is blind: `validate_dispatch.py`
(dispatch_result), `cap_web_fetch.py` (web-cap), `finalize.py` (result/sentinel).
Enforce the flush/latency budget (§4.3). Skip per-tool timing spans — native
`claude_code.tool` already covers them.

**What the current orchestration plan must NOT preclude:**
- Keep `alpha.runner.spawn_main_agent`/`spawn_sub_agent` as live transactions
  (parents for propagation).
- Keep the spawn-time env-injection sites (`cloud_run_client.py:48-62`,
  `modal_client.py:82-99`, `modal_app.py:93-102`) extensible — agent Sentry adds
  env keys there.
- Keep the scrubber in `infra/observability.py` as the canonical implementation so
  a vendored hook copy can be diffed against it.
- Do not make the runner sampling decision in a way that can't be exported as
  baggage (head-based) — agents must inherit it.
