# Cleanup / De-fat Plan

Goal: cut sponsor-integration fat so the core (web → orchestrator → Redis → runner →
Modal/CloudRun → results) is the only thing left to reason about. Each cut is an
independent, shippable step on its own branch; tests stay green between steps.

Order: **Browserbase → wandb → Sentry/OTEL** (low → higher coupling). wandb +
Browserbase share `capture_wandb.py`, so they collapse into one combined cut in practice.

---

## Cut 1 — Browserbase + wandb (combined; the "evidence dashboard" path)

The sub-agent fallback (matplotlib PNG + `result.json` → GCS → main agent) already
exists and stays. We're only removing the live-dashboard-screenshot layer.

**Delete**
- `agent/sub-agent/scripts/capture_wandb.py`   (browserbase screenshot of the wandb run)
- `agent/sub-agent/scripts/wandb_run.py`        (deterministic wandb run-id helper)
- `scripts/setup_browserbase_context.py`
- `scripts/test_subagent_wandb.py`
- `tests/test_wandb_capture.py`

**Edit**
- `agent/sub-agent/scripts/train_ppo.py` — drop `_wandb_init` (~341-359) + the `log_cb`/
  `wandb.log` wiring (381, 391-393); keep the matplotlib PNG artifact path.
- `infra/config.py` — remove `wandb_entity`, `browserbase_context_id`, `browserbase_project_id`.
- `infra/modal_app.py` — remove params (134-136) + env injection (185-193) + comment block.
- `runner/modal_client.py` — remove `wandb_entity` / `browserbase_*` kwargs (53-57).
- `agent/sub-agent/CLAUDE.md` — remove the "Weights & Biases" + "If wandb/Browserbase
  doesn't work" sections (~50 lines). Keep the matplotlib-PNG fallback guidance.
- `web/app/(shell)/integrations/page.tsx` — remove the W&B + Browserbase cards.
- `scripts/deploy_modal.sh` — drop `WANDB_API_KEY` / `BROWSERBASE_API_KEY` from the
  `alpha-secrets` Modal secret.

**Leave (low value, vendored):** wandb lines in `agent/sub-agent/reference/cleanrl/*` —
reference copies, not on the run path. Strip later if desired.

**Verify:** `pytest -q` green; sub-agent still writes `result.json` + a PNG artifact.

---

## Cut 2 — Sentry + OpenTelemetry (the woven-in one)

Replace inline instrumentation with stdlib `logging`. **Keep `scrub()`** as a plain util.

**Delete**
- `infra/observability.py` → replace with a 1-purpose `infra/scrub.py` (just `scrub()`).
- `tests/test_agent_otel.py`
- `docs/sentry-observability-plan.md`, `docs/agent-sentry-prereqs.md`
- Sentry/OTEL sections of `docs/ops-runbook.md`.
- Keep `tests/test_scrubber.py` (retarget import to `infra/scrub.py`).

**Edit (drop the dependency)**
- `pyproject.toml` — remove `sentry-sdk[fastapi]>=2.35` from `dependencies`.
- `infra/modal_app.py` — remove `sentry-sdk[fastapi]` from the image (line 38) + the
  OTEL static-config comment (178-183).

**Edit (remove instrumentation; swap to logging where an error was captured)**
- `infra/store.py` — drop `import sentry_sdk` + `add_breadcrumb` block (349); keep `scrub`.
- `runner/loops.py` — remove every `start_transaction`/`start_span`/`capture_exception`/
  `add_breadcrumb` + `tag_alpha`; replace exception captures with `logger.exception(...)`.
- `runner/internal_api.py` — remove sentry span/set_tag/tag_alpha.
- `orchestrator/api.py` — remove `init_observability("api")`.
- `runner/cloud_run_client.py` — remove the OTEL env block (65-83).
- `infra/config.py` — remove `agent_otel_enabled`, `otel_otlp_endpoint`, `otel_otlp_headers`.
- `scripts/smoke_infra.py`, `scripts/run_depth0.py`, `scripts/smoke_modal.py` — remove
  `init_observability(...)` calls.
- `.env.example` — remove the Sentry + Agent-OTEL blocks (70-88).
- `scripts/deploy_cloudrun.sh` / `scripts/deploy_modal.sh` — remove SENTRY_DSN / OTEL wiring.

**Verify:** `pytest -q` green; `uvicorn` boots; a local run completes (`ALPHA_LOCAL_SIM`).

---

## Second pass (NOT in this plan — flagged for later)

- `infra/store.py` is one 27 KB file doing state+queue+eventbus+budget+transcripts.
  Split along those seams (your own 800-line rule).
- Clerk auth, Redis leadership election, `runner/local_sim.py`, dual dispatch backends —
  real complexity, but defer the decision until the sponsor fat is gone and the core is clear.

## Rough fat removed
~8-10 files deleted, 1 core dependency dropped, ~5 core files de-noised (the runner hot path),
3 docs removed. Net: the runner loops + store read clean, no dead integration config.
