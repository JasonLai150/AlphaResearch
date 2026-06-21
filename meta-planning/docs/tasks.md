# AlphaResearch — Tasks

Legend: `[x]` done & verified · `[~]` code exists but unverified/partial · `[ ]` not started.
Milestones **M0→M7** are ordered by dependency. Each item names the file to touch so it's
pickup-able cold. The "why" for each milestone lives in `plan.md`.

## Backbone (done)
- [x] Repo scaffold + infra seam (`infra/store` · `infra/dispatch` · `infra/schemas`)
- [x] Guardrails: max_depth · atomic fanout (`claim/release_fanout`) · atomic budget (`decr/incr_budget`)
- [x] Store seam verified live (`scripts/smoke_infra.py`: RedisJSON docs, budget, children, event stream)
- [x] Redis Cloud client — resilient timeouts/keepalive/retry (`store.get_redis`), verified live
- [x] Agent harness FILES: main-agent + sub-agent `CLAUDE.md` + `settings.json` + skills + hooks
- [x] Infra→runner handoff seam: API enqueues `sessions:queue`; dispatch runs experiment jobs only
- [x] FastAPI + SSE: `POST /sessions`, `GET /sessions/{id}/stream` (`orchestrator/api.py`)
- [x] Next.js shell wired to real endpoints, builds clean (`web/`) — charts/tree still stubbed (see M6)

## Backend MVP — DELIVERED in PR #8 (branch `docker-GCP-modal`)
This PR builds the runtime that M0–M2 + M7 called for, on the **Cloud-Run-Job main-agent**
architecture (revision of the original plan): main-agent = Cloud Run Job, sub-agents = Modal
Functions, dispatch via an authenticated internal HTTP API (no shared FS to the main agent).
See `docs/backend-mvp-notes.md` for the full SEV-fix map + the one remaining gap.
- [x] **M0 — test net**: `tests/` stood up — store, internal API, hooks, main-agent scripts,
      runner loops, cloud-run client, gcs uploader, full API, e2e smoke (71 tests, fakeredis).
- [x] **M1 — the runner** (`runner/`): session/dispatch/reconcile loops; spawns main-agent Cloud
      Run Job (`cloud_run_client`) + sub-agent Modal Fns (`modal_client`); reconciles lifecycle,
      ships artifacts to GCS; single-leader Redis lease (replaces the XREADGROUP design).
- [x] **Internal API** (`runner/internal_api.py`): events / transcript / dispatch / children with
      per-session ephemeral-token auth + dispatch depth/parent/fanout validation; hidden from OpenAPI.
- [x] **M2 — containers**: `deploy/{main-agent,sub-agent,api}.Dockerfile` (api image build-verified).
- [x] **M7 — deploy tooling**: `scripts/gcp_bootstrap.sh` (APIs/repo/bucket/SAs/IAM/secrets) +
      `scripts/deploy_cloudrun.sh` (service + main-agent Job); runbook `docs/gcp-setup.md`.
- [x] SEV-1..13 ship-blocker/this-week fixes applied + two adversarial-review passes folded in.
- [x] Schema v2 (Job.backend/sandbox_id, Message, +queued/+cancelled; dropped modal_call_id).

## Cloud bring-up (status)
- [~] GCS artifacts: code complete + tested via mocks; live GCS path not yet exercised end-to-end
- [ ] Modal app deployed — NOT deployed (`modal deploy infra/modal_app.py` pending; needs secrets)
- [ ] Cloud Run deployed — scripts ready but not yet run against the project (APIs were disabled)

## Cloud bring-up — DONE (2026-06-21)
- [x] GCP bootstrap run live (APIs, AR repo, bucket, 3 SAs+IAM, secrets)
- [x] Modal deployed (`sub_agent` + `run_job`), py3.11 (envpool cp311) — green
- [x] Cloud Run deployed: service `alpha-api` (`…ziyr677nma-uc.a.run.app`) + job `alpha-main-agent`
- [x] Backbone proven live: `POST /sessions` → runner → real Cloud Run Job spawn → Redis state

## Path to v1 e2e — two PRs (see `v1-rollout.md` for full detail)
Found: agents spawn but **idle** (interactive `claude`, no goal in container); and the
Modal volume is broken **both** directions (dispatch out + result back), not just return.
- [x] **PR1 `feat/headless-agents`** — `GET /internal/bootstrap` (goal+mode) · `claude -p`
      launchers · non-root `agent` user (claude blocks --dangerously-skip-permissions as root).
      **Verified live:** main agent boots headless, fetches goal, dispatches 3 sub-agents.
- [x] **PR2 `feat/two-way-push`** (code) — dispatch record as Modal arg · `POST /internal/result`
      (base64 artifacts → GCS) · reconcile reads Redis · Modal Volume removed. 77 tests pass.
      Runner also needs Modal creds (`MODAL_TOKEN_*` secrets) to spawn from Cloud Run — added.
- [~] **M3/M4 round-trip** superseded by PR1+PR2 (the volume bridge is removed, not hydrated).
      PR2 deploy + live e2e verification pending.
- [x] **Sentry observability** (`sentry` branch) — runner transactions, internal-API spans, event
      breadcrumbs, scrubber. Verified live: `DefaultCredentialsError` + spawn failures captured in Sentry.
- [x] **Agent OTEL Layer A** — opt-in (`ALPHA_AGENT_OTEL_ENABLED`); runner injects Claude Code native-OTEL
      env vars + W3C `TRACEPARENT` into both agent spawns; deploy scripts carry static config. 96 tests pass.
- [ ] **M5 — real RL training**: `run_experiment_real` still delegates to the synthetic stub; add a
      short minigrid+PPO loop (lazy torch/sb3) and the deps to the Modal image.
- [x] **M6 — web UI live demo**: recharts `JobNode.rewards`, real parent/child tree via
      `parentJobId`, `Last-Event-ID` resume + reconnect. Frontend-complete pass on
      `feat/frontend-complete`: toast + full error/empty/loading UX, responsive drawers,
      Vitest+RTL suite (37) + backend resume/error tests, eslint/prettier. Live e2e re-verify pending (Redis was down).
- [ ] **M7 — execute the deploy**: run `gcp_bootstrap.sh` + `deploy_cloudrun.sh` + `modal deploy`,
      then verify Redis Cloud reachable from Cloud Run egress + a `/healthz` smoke.
