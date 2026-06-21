# Verifying GCP deployments

A green `scripts/deploy_cloudrun.sh` only proves the `gcloud` **control-plane** calls
returned 0. It does **not** prove the deployment actually works on GCP's side — the new
revision can crash-loop on boot, a secret can fail to mount, or the agent Job image can be
broken and you won't find out until the first real chat.

`scripts/verify_deploy.sh` checks the live **runtime**, fast (~30–90s), and is safe to run
on every deploy and in CI.

```bash
./scripts/verify_deploy.sh            # all checks; exits non-zero if any required check fails
SKIP_JOB=1 ./scripts/verify_deploy.sh # skip the Job execution (no Anthropic API spend)
```

It also runs automatically at the end of `deploy_cloudrun.sh` (set `SKIP_VERIFY=1` to skip).

## What it checks

| # | Check | Why a green deploy doesn't already prove it |
|---|-------|---------------------------------------------|
| 1 | **Service revision Ready** — `latestReady == latestCreated` and the `Ready` condition is `True` | If the new revision crash-loops on boot, `gcloud run deploy` can still "succeed" while GCP keeps serving the **old** revision. |
| 2 | **Live `/health`** returns `{"ok":true}` | Proves the container booted *and* loaded secrets + verified Redis on startup — so it transitively validates Secret Manager + IAM. |
| 3 | **No `ERROR`-level logs** in the last 10m (Cloud Logging) | Surfaces startup tracebacks that don't fail the health check. |
| 4 | **Main-agent Job smoke execution** — `gcloud run jobs execute --update-env-vars=ALPHA_SMOKE=1 --wait` | A *created* Cloud Run Job is never exercised until the first real chat. The smoke run does a real `claude` round-trip inside the deployed image, proving the image boots + the service account + the mounted `ANTHROPIC_API_KEY` + network egress all work — in ~10–60s, not a 4h agent run. |
| 5 | **Modal sub-agent app** is deployed (best-effort; skipped if the `modal` CLI isn't installed) | Sub-agents run on Modal, not GCP; deployed separately. |

Check 4 is backed by `ALPHA_SMOKE=1` in `agent/main-agent/launch.py`: when set, the
launcher skips the runner bootstrap, validates the CLI + key, runs one cheap Haiku
round-trip, and exits with that round-trip's status — so `--wait` surfaces any failure.
The flag is passed as a **per-execution override**, so it never mutates the Job spec.

## Gotcha: the health route is `/health`, NOT `/healthz`

Google Front End **reserves the exact path `/healthz`** on `*.run.app` and returns its own
`404` at the edge *before the request reaches the container*. A `/healthz` route is
therefore silently unreachable from outside Cloud Run, even though the app registers it.

Verified empirically on `alpha-api`: every other path (`/health`, `/livez`, `/readyz`,
`/nonexistent`, …) reaches the container — only `/healthz` is intercepted. The tell is the
`x-cloud-trace-context` response header: present when the request reached the app, absent
when GFE answered at the edge. `verify_deploy.sh` uses that header to distinguish "app is
down" from "edge intercept" and will tell you to rename the route if it sees the latter.

For this reason the orchestrator's health endpoint is `/health` (see `orchestrator/api.py`).
Don't rename it back to `/healthz`.
