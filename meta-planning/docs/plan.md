# AlphaResearch — Plan

Autonomous-research app: a Claude "lead" agent decomposes an RL research goal and
recursively dispatches sub-agents into isolated sandboxes, which run experiments and
report summaries up. One human interface; results stream live to a web UI.
Full design + rationale: [`design.md`](./design.md).

## Architecture (one-liner)
Two layers, two seams. **Agent layer** = Claude Code CLI containers
(`agent/{main,sub}-agent/`) dispatching by file (`.dispatched/<job_id>.json` written by
`dispatch_subagent.py`, schema-validated by `agent/main-agent/scripts/schemas.py`).
**Infra layer** = experiment-kind jobs through `infra/{store,dispatch,schemas}`. **Redis**
= state/events/queue/budget; **Modal** = experiment compute; **GCS** = artifacts; SSE = a
pure Redis Stream tailer.

## Status (2026-06-20)
- Infra seam + local backend: working (experiment-kind path; agent path is now files-only).
- Cloud backplane fully wired & verified: **Redis Cloud + GCS + Modal** sandbox round-trip
  (local → spawn → sandbox writes shared Redis/GCS → read back).
- Agent harness flipped to **Claude Code CLI** (files-only, no SDK loop): main-agent
  + sub-agent each have `CLAUDE.md` + `.claude/settings.json` + `skills/` + hooks; the
  containers boot `claude --dangerously-skip-permissions`. Dispatch is a Bash call to
  `scripts/dispatch_subagent.py` validated by a `ResearchPlan` schema + PreToolUse hook;
  WebFetch capped by PostToolUse hook.
- Agent-harness Dockerfiles landed (`deploy/{main,sub}-agent.Dockerfile` + `.dockerignore`):
  `python:3.12-slim-bookworm` + Node 22 + `@anthropic-ai/claude-code` + `pydantic` + the agent
  workspace; sub-agent additionally bakes `envpool==0.8.4 / gymnasium / minigrid / numpy /
  matplotlib` (amd64 forced for the EnvPool wheel). Both ENTRYPOINT `claude
  --dangerously-skip-permissions`. No `infra/` or `orchestrator/` inside — the orchestrator
  service Dockerfile is a separate Phase-6 concern.
- Not yet proven: real Claude lead agent orchestrating over Modal end-to-end; live web demo;
  runner that turns `.dispatched/*.json` records into actual sub-agent containers.

## Next
- Build the runner that watches `.dispatched/` and spawns sub-agent containers
  (Modal or Docker) per dispatch record; write back `<job_id>.result.json`.
  Seam ready: API enqueues `sessions:queue`; infra runs experiment jobs only and
  leaves agent jobs `pending` for the runner (deleted-`run_agent` refs removed).
- End-to-end main-agent container run via the runner (CLI emits `.dispatched/*.json` →
  runner spawns sub-agent containers → results back); then API + web UI live demo.
- Replace synthetic experiment stub with real minigrid+PPO training.
- Cloud Run deploy (Phase 6).

## Open assumptions to challenge
- Experiments are still **synthetic** (deterministic stub), not real RL training.
- GCS bucket is **public-read** for the demo (revertible IAM binding).
- Coordination is P0 "summaries-up"; the population/synthesis research loop is deferred.
