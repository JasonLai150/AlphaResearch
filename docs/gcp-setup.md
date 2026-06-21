# GCP setup & deploy runbook — AlphaResearch backend

Everything someone with project permissions needs to stand up the backend on GCP +
Modal. Two scripts do the work; this doc says who runs them, with what inputs, in
what order.

```
Cloud Run SERVICE  alpha-api        FastAPI + runner loops      (1 instance)
Cloud Run JOB      alpha-main-agent main agent, 1 exec/chat     (triggered by runner)
Modal FUNCTION     sub_agent        1 per dispatched idea
Redis Cloud        state + queues + SSE bus (external; you provide the URL)
GCS                gs://<project>-artifacts   plots/checkpoints
```

---

## 0. Prerequisites

**Tools** (on the machine running the deploy): `gcloud`, Docker with `buildx`,
Python `uv`, and the Modal CLI (`pip install modal`).

**Permissions** — the operator running `gcp_bootstrap.sh` needs, on the project,
either **`roles/owner`** or all of: `serviceusage.serviceUsageAdmin`,
`resourcemanager.projectIamAdmin`, `iam.serviceAccountAdmin`,
`iam.serviceAccountKeyAdmin`, `artifactregistry.admin`, `storage.admin`,
`secretmanager.admin`, `run.admin`.
Check who you are: `gcloud auth list` and `gcloud config get-value project`.
> Note: a prior check found the project APIs disabled and the active account
> (`chensam178@gmail.com`) lacked `storage.buckets.list`. Make sure the active
> account is a project Owner before running the bootstrap, or switch with
> `gcloud config set account <you@…>`.

**Secret values you must obtain** (the bucket SA key is auto-minted):
| Secret | Where it comes from |
|---|---|
| `anthropic-api-key` | console.anthropic.com → API keys (`sk-ant-…`) |
| `alpha-redis-url`   | your Redis Cloud database connection URL (`redis://default:…@host:port`) |
| `gcs-sa-key`        | **auto-created** by `gcp_bootstrap.sh` (a base64 SA key) |

---

## 1. Bootstrap the project (one-time)

Enables APIs, creates the Artifact Registry repo, the GCS bucket, three service
accounts + their IAM, and the secrets:

```bash
export PROJECT=alpharesearch-500100          # or your project id
export ANTHROPIC_API_KEY=sk-ant-...          # populates the anthropic-api-key secret
export ALPHA_REDIS_URL='redis://default:...@host:port'   # populates alpha-redis-url
bash scripts/gcp_bootstrap.sh
```

Idempotent — safe to re-run. If you omit `ANTHROPIC_API_KEY` / `ALPHA_REDIS_URL`,
it skips those secrets (it prints how to add them later) and still does everything
else. What it creates:

- **APIs:** run, artifactregistry, secretmanager, storage, cloudbuild, iam, iamcredentials
- **Artifact Registry:** `${REGION}-docker.pkg.dev/${PROJECT}/alpha`
- **Bucket:** `gs://${PROJECT}-artifacts`
- **Service accounts + IAM:**
  - `alpha-orchestrator` — `run.developer` (trigger Jobs), `secretmanager.secretAccessor`, `serviceAccountUser` on the agent SA
  - `alpha-main-agent` — `secretmanager.secretAccessor`
  - `alpha-gcs` — `storage.objectAdmin` on the bucket; its key → the `gcs-sa-key` secret
- **Secrets:** `gcs-sa-key` (auto), `anthropic-api-key` + `alpha-redis-url` (if values provided)

---

## 2. Deploy the Cloud Run service + main-agent Job

```bash
bash scripts/deploy_cloudrun.sh
```

Builds + pushes the `api` and `main-agent` images, deploys `alpha-api` (running as
`alpha-orchestrator`, `--max-instances=1`), creates/updates the `alpha-main-agent`
Job (running as `alpha-main-agent`), then rewrites `ALPHA_INTERNAL_RUNNER_URL` to the
service's real URL. Prints the URL on success.

> `--max-instances=1` keeps the MVP single-instance; the runner's Redis leader lease
> makes it safe to raise later.

---

## 3. Deploy the sub-agents to Modal

```bash
pip install modal && modal token new          # one-time auth
# Create the shared Modal secret the sub_agent/experiment functions read:
bash scripts/deploy_modal.sh                  # bundles ANTHROPIC_API_KEY + REDIS_URL + GCS key (base64)
modal deploy infra/modal_app.py               # deploys sub_agent (+ run_job)
```

The Modal `alpha-secrets` secret must carry `ANTHROPIC_API_KEY`, `REDIS_URL` (or
`ALPHA_REDIS_URL`), and `GOOGLE_APPLICATION_CREDENTIALS_B64`. The runner injects the
per-session token + runner URL into each sub-agent at spawn — those are NOT in the
shared secret (SEV-4).

---

## 4. Verify

```bash
URL=$(gcloud run services describe alpha-api --region=us-central1 \
        --format='value(status.url)')
curl "$URL/healthz"                                   # {"ok": true}
curl -XPOST "$URL/sessions" -H 'content-type: application/json' \
     -d '{"user_id":"u_1","goal":"improve sample efficiency on DoorKey"}'
# -> {"session_id":"s_...","root_job_id":"j_..."}
curl "$URL/sessions/<sid>/full"                        # session + job tree + transcript
# live stream: curl -N "$URL/sessions/<sid>/stream"
```

---

## ⚠️ Before you expect a full round-trip

A real cloud run will create the session and spawn the **main agent**, but
**sub-agent results will not flow back yet**: the runner reads sub-agent results from
a local volume path, and Cloud Run cannot mount a Modal Volume. Fix the volume bridge
first (push-based `/internal/result`, or Modal-SDK reads) — see
[`backend-mvp-notes.md`](backend-mvp-notes.md) → "KNOWN GAP". Until then, deploy is
fine for exercising session creation, the main agent, SSE, and `/full`.

---

## Re-populating a secret later

```bash
printf '%s' 'sk-ant-...' | gcloud secrets versions add anthropic-api-key --data-file=-
printf '%s' 'redis://...' | gcloud secrets versions add alpha-redis-url   --data-file=-
```

## Teardown (optional)

```bash
gcloud run services delete alpha-api --region=us-central1
gcloud run jobs delete alpha-main-agent --region=us-central1
modal app stop alpharesearch
# bucket + secrets + SAs left in place; delete manually if you want a clean slate.
```

## Troubleshooting

- **`PERMISSION_DENIED … API has not been used`** → you skipped step 1, or the active
  account isn't an Owner. Re-run `gcp_bootstrap.sh` as an Owner.
- **`secret 'X' missing`** from the deploy → the secret has no value; add a version (above).
- **Artifact upload 403 in logs** → the `gcs-sa-key` secret is stale/missing; re-run
  `gcp_bootstrap.sh` to mint a fresh key.
- **Two runners / double spawns during deploy** → expected to be prevented by the
  leader lease; if seen, check Redis connectivity (`alpha-redis-url`).
