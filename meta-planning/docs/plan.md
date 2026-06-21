# AlphaResearch — Plan

Autonomous-research app: a Claude "lead" agent decomposes an RL research goal and
recursively dispatches sub-agents into isolated sandboxes, which run experiments and
report summaries up. One human interface; results stream live to a web UI.
Full design + rationale: [`design.md`](./design.md).

## Architecture (one-liner)
Self-similar `run_agent` at every depth, split from infra by a stable seam
(`infra/store` + `infra/dispatch` + `infra/schemas`). **Redis** = state + event bus +
queue + budget; **Modal** = sandbox compute; **GCS** = artifacts. SSE = a pure Redis
Stream tailer.

## Status (2026-06-20)
- Infra seam + self-similar agent loop + local backend: working.
- Cloud backplane fully wired & verified: **Redis Cloud + GCS + Modal** sandbox round-trip
  (local → spawn → sandbox writes shared Redis/GCS → read back).
- Agent harness flipped to **Claude Code CLI** (files-only, no SDK loop): main-agent
  + sub-agent each have `CLAUDE.md` + `.claude/settings.json` + `skills/` + hooks; the
  containers boot `claude --dangerously-skip-permissions`. Dispatch is a Bash call to
  `scripts/dispatch_subagent.py` validated by a `ResearchPlan` schema + PreToolUse hook;
  WebFetch capped by PostToolUse hook.
- Not yet proven: real Claude lead agent orchestrating over Modal end-to-end; live web demo;
  runner that turns `.dispatched/*.json` records into actual sub-agent containers.

## Next
- Build the runner that watches `.dispatched/` and spawns sub-agent containers
  (Modal or Docker) per dispatch record; write back `<job_id>.result.json`.
  Seam ready: API enqueues `sessions:queue`; infra runs experiment jobs only and
  leaves agent jobs `pending` for the runner (deleted-`run_agent` refs removed).
- Run the full depth-0 agent loop over Modal; then API + web UI live demo.
- Replace synthetic experiment stub with real minigrid+PPO training.
- Cloud Run deploy (Phase 6).

## Open assumptions to challenge
- Experiments are still **synthetic** (deterministic stub), not real RL training.
- GCS bucket is **public-read** for the demo (revertible IAM binding).
- Coordination is P0 "summaries-up"; the population/synthesis research loop is deferred.
