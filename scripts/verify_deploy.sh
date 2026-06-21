#!/usr/bin/env bash
# High-fidelity post-deploy verification for the AlphaResearch GCP stack.
#
# A green `deploy_cloudrun.sh` only proves the gcloud *control-plane* calls returned 0.
# It does NOT prove the deployment actually works on GCP's side. This script checks the
# real runtime, fast (~30-90s), and is safe to run on every deploy / in CI:
#
#   1. Cloud Run SERVICE became Ready    — the new revision actually came up
#      (latestReady == latestCreated) and Ready=True. If it crash-looped, the deploy
#      "succeeded" but GCP is still serving the OLD revision.
#   2. Live /health                      — container booted AND loaded secrets + verified
#      Redis on startup (transitively validates Secret Manager + IAM). NOTE: /health,
#      not /healthz — GFE reserves "/healthz" on *.run.app and 404s it at the edge.
#   3. Cloud Logging error scan          — surfaces startup tracebacks the health check misses.
#   4. Main-agent JOB smoke execution    — executes the Job with ALPHA_SMOKE=1 (per-execution
#      override, does NOT mutate the spec) and WAITS. The launcher does a real `claude`
#      round-trip in the deployed image, so this proves the agent image boots + the SA +
#      mounted ANTHROPIC_API_KEY + egress all work. A created Job is otherwise never
#      exercised until the first real chat — this is the only quick way to catch a broken image.
#   5. Modal app (best-effort)           — confirms the sub-agent app is deployed, if the
#      modal CLI is available.
#
#   PROJECT=... REGION=... ./scripts/verify_deploy.sh        # all checks
#   SKIP_JOB=1 ./scripts/verify_deploy.sh                    # skip the Job execution (no API spend)
#
# Exits non-zero if any required check fails. Modal is best-effort (warn, not fail).
set -uo pipefail

PROJECT="${PROJECT:-alpharesearch-500100}"
REGION="${REGION:-us-central1}"
SERVICE="${SERVICE:-alpha-api}"
AGENT_JOB="${AGENT_JOB:-alpha-main-agent}"
MODAL_APP="${MODAL_APP:-alpharesearch}"
SKIP_JOB="${SKIP_JOB:-0}"
LOG_FRESHNESS="${LOG_FRESHNESS:-10m}"

fail=0
pass() { printf '  \033[32m✓\033[0m %s\n' "$1"; }
err()  { printf '  \033[31m✗\033[0m %s\n' "$1"; fail=1; }
warn() { printf '  \033[33m!\033[0m %s\n' "$1"; }
hdr()  { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

G=(gcloud --project="${PROJECT}" --quiet)

# 1. Service revision actually became Ready ---------------------------------------------
hdr "1/5 Cloud Run service '${SERVICE}' revision health"
read -r READY CREATED <<<"$("${G[@]}" run services describe "${SERVICE}" --region="${REGION}" \
    --format='value(status.latestReadyRevisionName, status.latestCreatedRevisionName)' 2>/dev/null)"
# Extract the Ready condition's status robustly (gcloud's projection .filter() is
# unreliable across versions — it returned all conditions here), so parse the JSON.
COND="$("${G[@]}" run services describe "${SERVICE}" --region="${REGION}" --format=json 2>/dev/null \
    | python3 -c 'import json,sys; cs=json.load(sys.stdin).get("status",{}).get("conditions",[]); print(next((c.get("status","") for c in cs if c.get("type")=="Ready"),""))' 2>/dev/null)"
URL="$("${G[@]}" run services describe "${SERVICE}" --region="${REGION}" \
    --format='value(status.url)' 2>/dev/null)"
if [[ -z "${CREATED}" ]]; then
    err "service not found (or no read access)"
elif [[ "${READY}" != "${CREATED}" ]]; then
    err "latest revision '${CREATED}' is NOT ready (serving old '${READY:-none}') — likely a crash loop on boot"
elif [[ "${COND}" != "True" ]]; then
    err "Ready condition is '${COND:-unknown}', not True"
else
    pass "revision '${CREATED}' Ready; serving at ${URL}"
fi

# 2. Live /health -----------------------------------------------------------------------
# NOTE: the path is /health, NOT /healthz — Google Front End reserves the exact path
# "/healthz" on *.run.app and 404s it at the edge before it reaches the container.
hdr "2/5 Live /health"
HEALTH_PATH="${HEALTH_PATH:-/health}"
if [[ -z "${URL}" ]]; then
    err "no service URL to probe"
else
    HDR_FILE="$(mktemp)"; BODY_FILE="$(mktemp)"
    CODE="$(curl -sS --max-time 15 -o "${BODY_FILE}" -D "${HDR_FILE}" -w '%{http_code}' \
        "${URL}${HEALTH_PATH}" 2>/dev/null)"
    BODY="$(cat "${BODY_FILE}" 2>/dev/null)"
    if [[ "${CODE}" == 2* ]] && [[ "${BODY}" == *'"ok"'*true* ]]; then
        pass "${URL}${HEALTH_PATH} -> ${CODE} ${BODY}"
    elif ! grep -qi 'x-cloud-trace-context' "${HDR_FILE}"; then
        # No trace header => the request was answered at the edge, not the container.
        err "${URL}${HEALTH_PATH} (HTTP ${CODE:-none}) never reached the container — intercepted at the GFE edge. If the route is named '/healthz', rename it (GFE reserves that exact path)."
    else
        err "${URL}${HEALTH_PATH} returned HTTP ${CODE:-none} body=${BODY:-<empty>}"
    fi
    rm -f "${HDR_FILE}" "${BODY_FILE}"
fi

# 3. Cloud Logging error scan (last ${LOG_FRESHNESS}) -----------------------------------
hdr "3/5 Recent ERROR logs (last ${LOG_FRESHNESS})"
ERRS="$("${G[@]}" logging read \
    "resource.type=cloud_run_revision AND resource.labels.service_name=${SERVICE} AND severity>=ERROR" \
    --freshness="${LOG_FRESHNESS}" --limit=10 --format='value(textPayload,jsonPayload.message)' 2>/dev/null)"
if [[ -n "${ERRS}" ]]; then
    err "found ERROR-level logs on the service:"
    printf '      %s\n' "${ERRS}" | head -20
else
    pass "no ERROR-level logs in the last ${LOG_FRESHNESS}"
fi

# 4. Main-agent Job smoke execution -----------------------------------------------------
hdr "4/5 Main-agent Job '${AGENT_JOB}' smoke execution"
if [[ "${SKIP_JOB}" == "1" ]]; then
    warn "SKIP_JOB=1 — skipping Job execution (image boot NOT verified)"
elif ! "${G[@]}" run jobs describe "${AGENT_JOB}" --region="${REGION}" >/dev/null 2>&1; then
    err "job '${AGENT_JOB}' not found"
else
    echo "  running: gcloud run jobs execute ${AGENT_JOB} --update-env-vars=ALPHA_SMOKE=1 --wait (real claude round-trip)"
    if "${G[@]}" run jobs execute "${AGENT_JOB}" --region="${REGION}" \
        --update-env-vars=ALPHA_SMOKE=1 --wait >/tmp/alpha-job-smoke.log 2>&1; then
        pass "Job execution succeeded — agent image boots, SA + secret + egress OK"
    else
        err "Job smoke execution FAILED — agent image is broken on GCP. Recent task logs:"
        EXEC="$("${G[@]}" run jobs executions list --job="${AGENT_JOB}" --region="${REGION}" \
            --limit=1 --format='value(name)' 2>/dev/null)"
        "${G[@]}" logging read \
            "resource.type=cloud_run_job AND resource.labels.job_name=${AGENT_JOB}" \
            --freshness=15m --limit=15 --format='value(textPayload,jsonPayload.message)' 2>/dev/null \
            | sed 's/^/      /' | head -25
        [[ -n "${EXEC}" ]] && echo "      execution: ${EXEC}"
    fi
fi

# 5. Modal sub-agent app (best-effort) --------------------------------------------------
hdr "5/5 Modal sub-agent app '${MODAL_APP}' (best-effort)"
if ! command -v modal >/dev/null 2>&1; then
    warn "modal CLI not installed locally — skipping (sub-agents deploy separately)"
elif modal app list 2>/dev/null | grep -qw "${MODAL_APP}"; then
    pass "Modal app '${MODAL_APP}' is deployed"
else
    warn "Modal app '${MODAL_APP}' not found in 'modal app list' — run: modal deploy infra/modal_app.py"
fi

# Verdict -------------------------------------------------------------------------------
echo
if [[ "${fail}" -eq 0 ]]; then
    printf '\033[1;32mDEPLOY VERIFIED — GCP runtime is healthy.\033[0m\n'
    exit 0
else
    printf '\033[1;31mDEPLOY VERIFICATION FAILED — see ✗ above.\033[0m\n'
    exit 1
fi
