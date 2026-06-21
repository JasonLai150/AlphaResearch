# AlphaResearch — Tasks

## Infra & backbone
- [x] Repo scaffold + infra seam (`store` / `dispatch` / `schemas`)
- [x] Self-similar `run_agent` + tools (dispatch/report/query/finalize)
- [x] Guardrails: max_depth / atomic fanout / atomic budget
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
- [ ] Dockerfiles + entrypoints (`claude --dangerously-skip-permissions`) for both containers
- [ ] Runner: watch `.dispatched/*.json` → spawn sub-agent container → write `<job_id>.result.json`
- [x] Rewire infra to runner handoff: removed deleted-`run_agent` imports; API enqueues
      `sessions:queue`; dispatch/modal run experiment-only; worker/run_depth0 are seams
      (imports green, ruff clean, `smoke_infra` passes)

## Next
- [ ] Full depth-0 Claude agent loop over Modal (`scripts/run_depth0.py`)
- [ ] API + web UI live demo over the cloud backplane
- [ ] `run_experiment_real`: real minigrid+PPO training (currently delegates to stub)
- [ ] `orchestrator/runner.py`: reconcile Modal call status → job status (TODO stub)
- [ ] Redeploy Modal image before flipping `max_depth` ≥ 2 (nested async spawn)
- [ ] Cloud Run deploy: api / worker / web (Phase 6)
- [ ] Unit + e2e tests (none yet; `tests/` dir missing)
