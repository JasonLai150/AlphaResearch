# Demo-prep handoff — prebaked trainer + constrained problem + warm pool

Branch: **`feat/demo-prep-trainer`** (off `main` @ `c9f24dd`). Pushed. 196 tests green,
ruff clean (the 43 remaining ruff errors are pre-existing vendored `reference/cleanrl/`).
Plan: `~/.claude/plans/twinkling-swinging-volcano.md` ("Demo-Prep Optimizations").

## Goal
Make a live demo fast + reliable. Four problems, all addressed:
1. constrain to a small RL search space, 2. trim image/build, 3. faster Modal training,
4. kill the ~5-min first-chat cold start.

## What changed

**A. Prebaked parameterized trainer (the big one — #1 reliability + #3 speed)**
- NEW **`agent/sub-agent/scripts/train_ppo.py`**: one tested PPO. An idea = `--intervention
  "k=v,k=v"` knob overrides (no per-run code authoring). Runs **baseline + intervention**,
  logs to wandb (via `wandb_run.init_wandb`), writes `training_curves.png` + `metrics.json`,
  and **always writes `/workspace/result.json`** → eliminates the "no result.json" crash
  class. Uses **envpool** (vectorized; it DOES ship MiniGrid — verified, see below), falls
  back to gymnasium+`minigrid` when envpool is absent (so it runs/test off-Modal).
- `agent/sub-agent/CLAUDE.md`: rewritten — "run `train_ppo.py`, don't author training code."

**B. Constrained search space (#1)**
- `agent/main-agent/scripts/schemas.py`: `ALLOWED_ENVS={"MiniGrid-Empty-5x5-v0"}`,
  `MAX_BUDGET_STEPS=50_000`, `TUNABLE_KNOBS`; `ResearchPlan` validators reject a bad env,
  over-budget, or non-knob `base_hparams`. Enforced by the existing `validate_dispatch.py`
  PreToolUse hook → the main agent **cannot** dispatch out-of-bounds work.
- `agent/main-agent/skills/research/SKILL.md`: demo guardrails; 2–3 knob-intervention ideas;
  skip the web/baseline hunt (scaffold is fixed).

**C. Image / build trim (#2 — modest, since wandb+Browserbase kept)**
- `deploy/sub-agent.Dockerfile`: dropped `tensorboard`; merged 3 pip layers → 2 (faster
  builds/cache). Kept torch-CPU + envpool + minigrid + wandb + Browserbase. (api image was
  already lean — numpy/matplotlib are extras-only via `uv sync --no-dev`.)

**D. Cold start (#4)**
- `infra/modal_app.py`: `min_containers=1` on `sub_agent` (warm pool) + a new `warmup()`
  function (imports torch+envpool in the real image).
- `scripts/deploy_modal.sh`: post-deploy `modal run …::warmup` (catches a broken image at
  deploy, not first chat).

**Tests/harness:** `tests/test_train_ppo.py` (pure fns + guarded e2e smoke),
`tests/test_research_plan_guardrails.py` (env/budget/knob rejection),
`tests/test_dispatch_subagent.py` (`_valid_plan` updated to the demo shape), `tests/conftest.py`
(forces a valid `ALPHA_REDIS_URL` so a malformed local `.env` can't break collection).

## Correction worth recording
I initially claimed envpool doesn't support MiniGrid; **that was wrong.** Verified against
the pinned `envpool==1.2.5`: 1651 envs incl. `MiniGrid-Empty-5x5-v0` (`MiniGridGymnasiumEnvPool`,
Dict obs `{image (7,7,3), direction, mission}`, `Discrete(7)`). The Dockerfile comment already
said so. envpool stays; the trainer uses it.

## Deploy state (at handoff)
- **Modal: DEPLOYED + verified.** `modal deploy infra/modal_app.py` (75s) rebuilt the
  sub-agent image; `warmup` smoke passed (torch+envpool import OK). `sub_agent` now has
  `min_containers=1` (a warm container is standing — **idle cost until scaled to 0**).
  - NOTE: deploy Modal with **`modal deploy`**, NOT `deploy_modal.sh`, unless you also intend
    to recreate `alpha-secrets` from `.env` — the local `.env` has a **mangled `ALPHA_REDIS_URL`**
    (doubled / no scheme). `alpha-secrets` was last synced from GCP (funded key + wandb).
- **Cloud Run: DEPLOYED + verified.** `deploy_cloudrun.sh` rebuilt api + main-agent images
  (`v20260621-080428`, revision `alpha-api-00036-8rj`) with the schema caps + research skill;
  its smoke ran a real main-agent claude round-trip (boots, secret + egress OK). Same code
  generation as Modal → no skew.

## Open items / next steps
1. **wandb diagrams need runner env.** The trainer logs to wandb, but `capture_wandb.py`
   needs `WANDB_ENTITY` + `BROWSERBASE_CONTEXT_ID`/`BROWSERBASE_PROJECT_ID` on the Cloud Run
   runner (passed to sub-agents as Modal call args via `settings`). `deploy_cloudrun.sh` does
   NOT set these yet — until then runs fall back to the matplotlib `training_curves.png`.
   Set them (context id is in `.env`; `WANDB_ENTITY` must match the Browserbase context's wandb
   org) then redeploy the service.
2. **Scale the warm pool to 0 after the demo** (`min_containers` back to 0) to stop idle cost.
   For an all-instant fan-out of N ideas, set `min_containers=N` during the demo window.
3. **Fix local `.env` `ALPHA_REDIS_URL`** (mangled) for local `uvicorn`/scripts.
4. **Scope note:** the prebaked trainer narrows the research story to hyperparameter
   interventions on one env (by design, for demo reliability). The agent-authored path
   (`design.md` §8.G) remains the post-demo direction.

## Run a demo (after both deploys land)
```bash
URL=https://alpha-api-ziyr677nma-uc.a.run.app
curl -s -XPOST "$URL/sessions" -H 'content-type: application/json' \
  -d '{"user_id":"u_demo","goal":"improve PPO sample efficiency on MiniGrid-Empty-5x5"}'
# -> warm sub-agents run train_ppo.py in seconds; watch /sessions/<sid>/full for runs[]+artifacts[]
```
The first chat hits the warm pool (no 5-min wait); sub-agents are capped to Empty-5x5 / ≤50k
steps and run the prebaked trainer → fast, reliable, with a baseline-vs-intervention plot.

## Commits (newest first)
- `feat(demo): prebaked PPO trainer + constrained search space + warm pool`
