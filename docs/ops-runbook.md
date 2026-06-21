# Ops runbook — deploy & run AlphaResearch

Persisted commands so we stop hitting deploy-skew + manual-exec footguns. For
first-time project setup (APIs, SAs, secrets) see [`gcp-setup.md`](./gcp-setup.md);
this doc is the day-to-day "deploy the new code + run a session" reference.

## 0. Who owns what (read this first)

The whole system spans **three runtimes that deploy separately** — they drift if you
only update one. There is exactly one authoritative home for each:

| Thing | Authoritative home | Notes |
|---|---|---|
| Modal app `alpharesearch` (`sub_agent`, `run_job`) | Modal workspace **`laijason150`** | The Cloud Run runner's `MODAL_TOKEN_ID/SECRET` authenticate to **this** workspace. Deploy here, NOT your personal workspace. |
| Cloud Run service `alpha-api` (API + runner loops) | GCP project **`alpharesearch-500100`**, region **`us-central1`** | Live URL: `https://alpha-api-ziyr677nma-uc.a.run.app` |
| Cloud Run job `alpha-main-agent` (main agent, 1 exec/session) | same project/region | Triggered **by the runner**, never by hand (see §3). |

> **The #1 failure mode:** a teammate `modal deploy`s to *their own* workspace, so the
> shared `laijason150` Modal app stays stale while the Cloud Run runner (which holds
> `laijason150` tokens) keeps calling the old `sub_agent`. Symptom:
> `TypeError: sub_agent() got an unexpected keyword argument '...'`. **Always deploy Modal
> to `laijason150`** — check with `uv run modal profile current` (must print `laijason150`).
> If it doesn't, get the shared token: `uv run modal token set ...` (ask the owner).

## 1. Deploy after merging code

```bash
# Modal — sub-agent + run_job (rebuilds the sub-agent image from deploy/sub-agent.Dockerfile)
uv run modal profile current          # MUST be: laijason150
uv run modal deploy infra/modal_app.py

# Cloud Run — api/runner service + main-agent job (builds+pushes both images, rewrites RUNNER_URL)
bash scripts/deploy_cloudrun.sh
```

**Which to deploy for a given change:**

| You changed… | Deploy |
|---|---|
| `infra/modal_app.py`, `deploy/sub-agent.Dockerfile`, `agent/sub-agent/**` | **Modal** |
| `runner/**`, `orchestrator/**`, `infra/**` (control plane), `agent/main-agent/**`, `deploy/{api,main-agent}.Dockerfile` | **Cloud Run** |
| **A shared cross-boundary signature** — e.g. `spawn_sub_agent` / `sub_agent` args, the dispatch record, `/internal/*` bodies | **BOTH, together** |

> The traceparent outage was exactly the last row: `94cef73` added `traceparent=`/`baggage=`
> to *both* `runner/modal_client.py` (deployed via Cloud Run) and `infra/modal_app.py`
> (deployed via Modal), but only Cloud Run was redeployed. **Cross-boundary change ⇒ deploy both.**

Optional (only when sub-agent telemetry/secrets changed): refresh the Modal secret
before `modal deploy` — `bash scripts/deploy_modal.sh` (re-bundles `ANTHROPIC_API_KEY`,
`REDIS_URL`, GCS key, and the SENTRY/OTEL/wandb/Browserbase vars into `alpha-secrets`).
Not needed just to fix a code/signature skew.

## 2. Run a session — the ONLY correct trigger

A session is started by `POST /sessions`. The runner then mints a per-session token and
spawns the `alpha-main-agent` job with the right env injected. Do not start it any other way.

```bash
URL=https://alpha-api-ziyr677nma-uc.a.run.app

# create a session (user_id is required)
curl -s -XPOST "$URL/sessions" -H 'content-type: application/json' \
  -d '{"user_id":"u_1","goal":"improve PPO sample efficiency on MiniGrid-DoorKey-8x8"}' | python3 -m json.tool
# -> {"session_id":"s_...","root_job_id":"j_..."}

SID=s_...                                   # paste the id from above
curl -s "$URL/sessions/$SID/full" | python3 -m json.tool   # session + job tree + runs[] + transcript + artifacts
curl -N "$URL/sessions/$SID/stream"                         # live SSE event firehose
curl -s "$URL/healthz"                                      # {"ok": true}
```

A healthy run: `/full` shows the depth-0 job `running`, then `spawn` children, then each
child's `runs[]` with metrics + `artifacts[]` (GCS `https://…` URLs), then a synthesis.

## 3. Do NOT `gcloud run jobs execute alpha-main-agent`

Running the job by hand boots it with only its **base env** — which has no per-session
`ALPHA_INTERNAL_TOKEN` (the runner mints + injects that at spawn). The container aborts:

```
[launch] missing ALPHA_INTERNAL_RUNNER_URL / ALPHA_INTERNAL_TOKEN   # exit 1
```

This is operator error, not a bug — the message names both vars but it's the **token**
that's absent. To run the main agent, use `POST /sessions` (§2). The runner-driven path
already works; manual execs will always fail this check.

## 4. Diagnose a deploy skew

```bash
PROJECT=alpharesearch-500100 ; REGION=us-central1

# What CODE is each runtime actually running?
gcloud run services describe alpha-api --region=$REGION \
  --format="value(spec.template.spec.containers[0].image)"          # api/runner image tag (vYYYYMMDD-HHMMSS)
gcloud run jobs describe alpha-main-agent --region=$REGION \
  --format=yaml | grep -E "image:|lastModifier"                     # main-agent image tag
uv run modal app list                                               # Modal app + "Created at" = last deploy time

# Who triggered the recent main-agent runs? (alpha-orchestrator = runner ✓ ; a human = manual exec ✗)
gcloud run jobs executions list --job=alpha-main-agent --region=$REGION --limit=6
```

If the api image tag is newer than the Modal "Created at", suspect a cross-boundary skew
→ `uv run modal deploy infra/modal_app.py` (from workspace `laijason150`).

## 5. Logs

```bash
# main-agent job (one execution per session)
gcloud run jobs executions logs <execution-name> --region=us-central1
# api/runner service
gcloud run services logs read alpha-api --region=us-central1 --limit=100
# sub-agents (Modal) — filter to the current session's job ids from /full
uv run modal app logs alpharesearch
```
