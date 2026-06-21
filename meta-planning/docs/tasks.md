# AlphaResearch — Tasks

## Infra & backbone
- [x] Repo scaffold + infra seam (`store` / `dispatch` / `schemas`)
- [x] ~~Self-similar `run_agent` + tools (dispatch/report/query/finalize)~~ — SDK-loop era; superseded by the Claude Code CLI files-only flip (`agent/{main,sub}-agent/`).
- [x] Guardrails: max_depth / atomic fanout / atomic budget — `infra/dispatch.py` for experiment jobs; agent fan-out is enforced by the dispatch script + PreToolUse hook + runner.
- [x] Local backend e2e (`scripts/smoke_infra.py`)

## Cloud bring-up
- [x] Redis Cloud wired + verified (resilient client for variable latency)
- [x] GCS artifacts wired + verified (public-read demo; https URLs)
- [x] Modal app deployed (`scripts/deploy_modal.sh`, secret via base64)
- [x] Modal sandbox round-trip verified (`scripts/smoke_modal.py`)
- [x] Async spawn fix (`spawn.aio`) for parallel dispatch

## Agent harness (Claude Code CLI, files-only)
- [x] `agent/main-agent/`: CLAUDE.md + `.claude/settings.json` + skills (`research`, `dispatch-subagents`)
- [x] `agent/main-agent/scripts/`: `schemas.py` (ResearchPlan/Idea/DiversityTag) + `dispatch_subagent.py`
- [x] `agent/main-agent/.claude/hooks/`: `validate_dispatch.py` (PreToolUse Bash) + `cap_web_fetch.py` (PostToolUse Web*)
- [x] `agent/sub-agent/` (minimal): CLAUDE.md + `.claude/settings.json` (Web* denied) + `validated-findings` skill
- [x] Dockerfiles + entrypoints (`claude --dangerously-skip-permissions`) for both containers
      (`deploy/main-agent.Dockerfile`, `deploy/sub-agent.Dockerfile`, `.dockerignore`;
      sub-agent ships envpool/gymnasium/minigrid baked in, amd64 forced)
- [x] Runner: `runner/` package — session/dispatch/reconcile loops spawn main-agent (Cloud Run
      Job) + sub-agents (Modal), reconcile lifecycle, ship artifacts to GCS. Dispatch records
      arrive via `POST /internal/dispatch` (no shared FS); results via per-session Modal volume.
- [x] Rewire infra to runner handoff: removed deleted-`run_agent` imports; API enqueues
      `sessions:queue`; dispatch/modal run experiment-only; worker/run_depth0 are seams
      (imports green, ruff clean, `smoke_infra` passes)

## Backend MVP (this branch)
- [x] Schema v2 + store helpers (transcript, dispatch queue, child statuses, status index,
      full-session read, per-session tokens, leader lease, deterministic artifact ids)
- [x] Internal HTTP API (events/transcript/dispatch/children) — per-session token auth,
      dispatch depth/parent/fanout validation, hidden from OpenAPI
- [x] Agent hooks (events/transcript push; sub-agent atomic result + `.done` sentinel) + main-agent HTTP child scripts
- [x] API wiring: `POST /sessions {user_id,goal}`, `GET /sessions/{sid}/full`, runner startup + Redis ping
- [x] `deploy/api.Dockerfile` + idempotent `scripts/deploy_cloudrun.sh` (service + main-agent Job)
- [x] Unit + e2e tests (`tests/`): store, internal API, hooks, scripts, runner loops, cloud-run, gcs, full API, e2e smoke
- [x] SEV-1..13 ship-blocker/this-week fixes applied + adversarially reviewed

## Next
- [ ] Live cloud round-trip: real Cloud Run Job + Modal sub-agents end-to-end (mocks pass; cloud run pending)
- [ ] API + web UI live demo over the cloud backplane
- [ ] `run_experiment_real`: real minigrid+PPO training (currently delegates to stub)
- [x] ~~Redeploy Modal image before flipping `max_depth` ≥ 2 (nested async spawn)~~ — moot: CLI sub-agents are leaves (no in-container dispatch tool), so agent depth caps at 2 by design.
