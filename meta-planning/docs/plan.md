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

## Status (2026-06-20, audited)
- Infra seam + store + guardrails + local backend: working, **verified live** (`smoke_infra`).
- **Redis Cloud** seam verified live. **Modal+GCS** round-trip verified *once* @`ed90b69` but
  NOT reproducible from the committed tree (no app deployed, backend=local, blank bucket);
  the GCS read-back was never asserted. Modal app + GCS deploy need re-establishing.
- Agent harness is **files only** (CLAUDE.md + settings + skills + hooks, both agents) —
  no Dockerfiles/entrypoints exist yet, so no container boots `claude` today.
- API (FastAPI+SSE) and a Next.js shell exist and build, wired to real endpoints.
- **The runner does not exist.** `sessions:queue` has zero consumers; Modal jobs never
  reconcile (stick at `running`); depth-0 loop, sub-agent spawn, web demo all block on it.

## Next (milestones — see tasks.md for granular checkboxes)
- M0: fix false checkmarks + stand up `tests/` (regression net for everything below).
- M1: build the runner — `sessions:queue` consumer + `modal_call_id` reconcile. **Keystone.**
- M2: containerize the harness (Dockerfiles + entrypoints) — parallel with M1.
- M3: depth-0 Claude loop over Modal — first real end-to-end run.
- M4: sub-agent spawn + `.dispatched/` result write-back (recursion).
- M5: replace synthetic stub with real minigrid+PPO — parallel after M1.
- M6: web UI live demo (charts, tree, reconnect). M7: Cloud Run deploy (Phase 6).

## Open assumptions to challenge
- Experiments are still **synthetic** (deterministic stub), not real RL training.
- GCS bucket is **public-read** for the demo (revertible IAM binding).
- Coordination is P0 "summaries-up"; the population/synthesis research loop is deferred.
