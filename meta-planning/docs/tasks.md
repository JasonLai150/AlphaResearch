# AlphaResearch — Tasks

Legend: `[x]` done & verified · `[~]` code exists but unverified/partial · `[ ]` not started.
Milestones **M0→M7** are ordered by dependency; M2 and M5 can run in parallel. Each item names
the file to touch so it's pickup-able cold. The "why" for each milestone lives in `plan.md`.

## Backbone (done)
- [x] Repo scaffold + infra seam (`infra/store` · `infra/dispatch` · `infra/schemas`)
- [x] Guardrails: max_depth · atomic fanout (`claim/release_fanout`) · atomic budget (`decr/incr_budget`)
- [x] Store seam verified live (`scripts/smoke_infra.py`: RedisJSON docs, budget, children, event stream)
- [x] Redis Cloud client — resilient timeouts/keepalive/retry (`store.get_redis`), verified live
- [x] Agent harness FILES: main-agent + sub-agent `CLAUDE.md` + `settings.json` + skills + hooks (no container yet)
- [x] Infra→runner handoff seam: API enqueues `sessions:queue`; dispatch runs experiment jobs only
- [x] FastAPI + SSE: `POST /sessions`, `GET /sessions/{id}/stream` (`orchestrator/api.py`) — code complete
- [x] Next.js shell wired to real endpoints, builds clean (`web/`) — charts/tree still stubbed (see M6)

## Cloud bring-up (corrected — were false [x])
- [~] GCS artifacts: GCS + local-fallback code complete; **only local path asserted**, GCS path never tested
- [~] Async spawn (`spawn.aio`) + dispatch modal branch: code complete, not reproducibly verified
- [ ] Modal app deployed — **NOT deployed now** (`modal app list` empty; needs `gcs-sa-key.json` + `ALPHA_GCS_BUCKET`)
- [ ] Modal sandbox round-trip — verified once @`ed90b69` only; not reproducible (`.env` backend=local)

## M0 — Honest baseline + test net  (cheapest credibility win; do first)
- [ ] Fix overstatements: `plan.md:16-17` (Redis verified vs Modal/GCS verified-once), `plan.md:20-22` (no containers yet), `README.md:23` (no Cloud Run configs), `agent/__init__.py:3` (stale `run_agent` docstring)
- [ ] Create `tests/` (pyproject `testpaths` already points here): `__init__.py` + `conftest.py` with a fakeredis fixture (monkeypatch `store.get_redis`)
- [ ] `tests/test_store.py` — ids, sessions, jobs, atomic budget, fanout, event stream, `_normalize_last_id` (store.py:224)
- [ ] `tests/test_schemas.py` — Job/JobKind/RunResult + `ResearchPlan` diversity cap (`agent/.../schemas.py:97`)
- [ ] `tests/test_hooks.py` — `validate_dispatch.py` (unknown + dup idea) and `cap_web_fetch.py` (12KB cap)
- [ ] Convert `scripts/smoke_infra.py` → `tests/e2e/test_smoke_infra.py` behind `@pytest.mark.e2e` + REDIS env guard

## M1 — Build the runner  (KEYSTONE — every path is blocked on this)
- [ ] DECIDE + document the two distinct seams: (a) orchestration runner = Redis `sessions:queue` consumer + `modal_call_id` reconciler; (b) `.dispatched/` files = in-container main-agent↔sub-agent handoff. State they are separate (resolves tasks.md:22-vs-31 contradiction)
- [ ] `store.ensure_sessions_group()` — `XGROUP CREATE` on `SESSIONS_QUEUE` w/ MKSTREAM, swallow BUSYGROUP
- [ ] `store.read_sessions_queue()` + `store.ack_session()` — wrap `XREADGROUP`/`XACK`; export in `__all__`
- [ ] Running-jobs index: `SADD/SREM jobs:running` inside `store.set_job_status`; add `store.get_running_jobs()`
- [ ] `orchestrator/runner.py` reconcile loop (replace runner.py:19 TODO sleep): for each running job w/ `modal_call_id`, `modal.FunctionCall.from_id(...).get(timeout=0)` → on terminal/exception `set_job_status(done|failed)` + emit status event; wrap in try/except so dead calls → `failed`, not a hang
- [ ] Shared `_status()` event-envelope helper (lift from `experiment.py:110` into `infra/`) so runner + experiment emit identically
- [ ] Queue consumer in the same runner: `read_sessions_queue` → `get_root_job` → mark root running → ack (harness launch lands in M3)
- [ ] Entrypoint `python -m orchestrator.runner` running both loops; retire `worker.py` NotImplementedError
- [ ] `tests/test_runner.py` — fake `modal_call_id`, assert running→done/failed + status event; assert queued session marks root running + acks

## M2 — Containerize the harness  (parallel with M1; pure packaging)
- [ ] `agent/main-agent/Dockerfile` — node base, `npm i -g @anthropic-ai/claude-code`, python+pydantic for scripts, COPY harness, ENTRYPOINT wrapper
- [ ] `agent/sub-agent/Dockerfile` — same base + CLI, COPY sub-agent harness (settings already deny Web*)
- [ ] `entrypoint.sh` (both) — inject `ANTHROPIC_API_KEY`/`ALPHA_REDIS_URL`, seed goal/idea + job_id, `exec claude --dangerously-skip-permissions`
- [ ] `.dockerignore` (both) excluding `__pycache__`/`*.pyc` (currently committed under scripts/)
- [ ] `scripts/build_agent_images.sh` — build both + one-shot `claude --version` boot check
- [ ] Check tasks.md cloud line for Dockerfiles + fix `plan.md:20-22` wording once images build

## M3 — Depth-0 loop over Modal  (first real end-to-end behavior; MORALE milestone)
- [ ] New Modal fn in `infra/modal_app.py` that boots the main-agent image (today modal_app.py:60 refuses agent jobs): spawn w/ goal from `job.params`, secrets via `alpha-secrets`
- [ ] Runner's queue consumer launches that fn for agent-kind roots; record `modal_call_id` so M1's reconcile closes it
- [ ] Verify launched harness writes job/run/event records back to Redis so `api.py` SSE streams them
- [ ] `scripts/run_depth0.py` — add poll-and-print of root status (pending→running→done); stop just printing "waiting"
- [ ] Remove stale `agent/__init__.py:3` `run_agent` docstring
- [ ] `tests/e2e/test_depth0.py` (`@pytest.mark.e2e`) — enqueue → run runner → assert pending→running→done + finalize events

## M4 — Sub-agent spawn + result write-back  (the recursive value)
- [ ] Runner picks up each `./.dispatched/<job_id>.json` (written by `dispatch_subagent.py:107`) → spawn one sub-agent container per record (job_id + plan + assigned idea)
- [ ] Write `./.dispatched/<job_id>.result.json` on finish so the main-agent poll loop (`dispatch-subagents/SKILL.md:59`) terminates
- [ ] Change `dispatch-subagents/SKILL.md:28-31` from present-tense to reflect a now-real runner
- [ ] Enforce guardrails on spawn (reuse `claim_fanout`/`decr_budget`); **redeploy Modal image before flipping max_depth ≥ 2**
- [ ] `tests/e2e/test_subagent_roundtrip.py` — fake `.dispatched/<id>.json` → run spawn path (container mocked) → assert `<id>.result.json` with valid RunResult

## M5 — Real RL training  (parallel after M1; makes output meaningful)
- [ ] `run_experiment_real` (today `experiment.py:152` just delegates to stub): lazily import gymnasium+minigrid, build `env_id` from params, fall back to stub on ImportError
- [ ] Short PPO loop (lazy-import sb3/torch), read `total_steps`/`lr`/`trainer` from params; add deps to Modal image (`modal_app.py:22`)
- [ ] Emit `metric` envelopes `{step, reward, series:'eval/reward'}` matching stub (`experiment.py:60`); reuse `_try_plot` + `put_artifact`
- [ ] Strengthen `scripts/smoke_modal.py`: fetch `artifact:{aid}` + HTTP-GET the GCS URL (200, bytes match); preflight-fail if `ALPHA_GCS_BUCKET` blank
- [ ] `tests/e2e/test_experiment_real.py` — `total_steps=2000` on `MiniGrid-Empty-8x8-v0`, assert metric+summary events + RunResult done

## M6 — Web UI live demo  (the demoable payoff)
- [ ] Plot `JobNode.rewards` (already collected at `page.tsx:67`) with recharts (in `package.json:15`, unused)
- [ ] Real parent/child tree via `parentJobId` (replace `page.tsx:112` marginLeft indentation)
- [ ] EventSource resume: track + send `last_event_id` on reconnect (`api.py:62` supports it) + `onerror` reconnect
- [ ] `web/.env.local.example` (`NEXT_PUBLIC_API_URL`) + `web/README` (`pnpm install && pnpm dev`)
- [ ] Manual end-to-end pass: api + runner + depth-0 launch → submit goal → confirm spawn/metric/summary render

## M7 — Cloud Run deploy (Phase 6)  (last mile; deploy a working system)
- [ ] `deploy/Dockerfile.api` (uvicorn `orchestrator.api:app`), `Dockerfile.worker` (`python -m orchestrator.runner`), `Dockerfile.web` (next build/start)
- [ ] `deploy/deploy_cloudrun.sh` — build → push to Artifact Registry → `gcloud run deploy` (worker `--no-cpu-throttling --min-instances=1`)
- [ ] Secret Manager: `ANTHROPIC_API_KEY`/`REDIS_URL`/GCS creds via `--set-secrets` (drop local `.env`)
- [ ] Verify Redis Cloud TLS reachable from Cloud Run egress; add to a smoke check
