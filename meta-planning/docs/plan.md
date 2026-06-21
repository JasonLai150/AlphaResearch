# AlphaResearch — Plan

Autonomous-research app: a Claude "lead" agent decomposes an RL research goal and
recursively dispatches sub-agents into isolated sandboxes, which run experiments and
report summaries up. One human interface; results stream live to a web UI.
Full design + rationale: [`design.md`](./design.md).

## Architecture (one-liner)
A Cloud Run **service** (`orchestrator/api.py` + the `runner/` asyncio loops) is the brain.
It spawns the **main agent** as a Cloud Run **Job** (Claude Code CLI, one per chat) and
**sub-agents** as **Modal Functions** (one per dispatched idea). Agents have no shared
filesystem with the runner — they push events/transcript/dispatch over an authenticated
internal HTTP API. **Redis** = state + event bus + queue + budget (single source of truth);
**GCS** = artifacts; sub-agents share a per-session **Modal Volume** with the runner. SSE = a
pure Redis Stream tailer.

## Status (2026-06-21)
- Infra **deployed + backbone proven live**: `POST /sessions` → runner → real Cloud Run Job
  spawn → Redis (GCP+Modal+Cloud Run all up). Two code gaps remain for an e2e run.
- Next = **PR1 headless agents** (bootstrap endpoint + `claude -p`) then **PR2 two-way push**
  (remove the Modal Volume). Detail in [`v1-rollout.md`](./v1-rollout.md).

## Status (2026-06-20, audited)
- Infra seam + store + guardrails + local backend: working, **verified live** (`smoke_infra`).
- **Redis Cloud** seam verified live. **Modal+GCS** round-trip verified *once* @`ed90b69` but not
  reproducible from the committed tree (no app deployed, backend=local); needs re-establishing.
- **The runner now EXISTS** (PR #8, branch `docker-GCP-modal`): `runner/` session/dispatch/reconcile
  loops, Cloud Run + Modal clients, internal API, per-session tokens, leader lease, GCS uploader —
  with a 71-test suite (fakeredis) and two adversarial-review passes. Agent **Dockerfiles** + a
  Cloud Run **deploy script** + a **GCP bootstrap script** also landed.
- **Not yet proven on real cloud:** the sub-agent result round-trip. Cloud Run can't mount a Modal
  Volume, so `reload_volume()` must hydrate via the Modal SDK (or sub-agents push results) before a
  live run completes — see `docs/backend-mvp-notes.md`. Real RL training + web demo still pending.
- **Web app — live + authed** (`web/`, branch `feat/dashboard-ui`): 3-pane console (Tailwind v4 +
  shadcn/ui + Lucide, `DESIGN.md`) wired to the live SSE stream (event-sourced reducer →
  tree/transcript/recharts metrics/artifacts), multi-turn chat (`POST /sessions/{id}/messages`),
  session history, resume/reconnect. Optional Clerk auth (app + API, graceful keyless dev fallback).
  Local dev runs end-to-end with no cloud via `ALPHA_LOCAL_SIM` (`runner/local_sim.py`). M6 ✅.
- **Frontend-complete pass** (`feat/frontend-complete`): toast + full error/empty/loading UX,
  pending-timeout, responsive drawers, real ContextBar, Vitest+RTL tests, eslint/prettier, deploy docs.

## Next (milestones — see tasks.md for granular checkboxes)
- M0 ✅ tests · M1 ✅ runner · M2 ✅ containers · M7 ✅ deploy tooling — delivered in PR #8.
- M3/M4: prove the depth-0 + sub-agent round-trip on real cloud (fix the volume bridge first).
- M5: replace the synthetic stub with real minigrid+PPO. M6: web UI live demo (charts, tree, resume).
- M7 (execute): run the bootstrap + deploy scripts + `modal deploy`; verify Redis reachable from Cloud Run.

## Open assumptions to challenge
- Experiments are still **synthetic** (deterministic stub), not real RL training.
- GCS bucket is **public-read** for the demo (revertible IAM binding).
- Coordination is P0 "summaries-up"; the population/synthesis research loop is deferred.
- Cloud Run ↔ Modal Volume access is the one unproven seam for a live sub-agent round-trip.
