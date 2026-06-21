#!/usr/bin/env bash
# scripts/gcp_bootstrap.sh
#
# ONE-TIME GCP project setup for the AlphaResearch backend. Run by someone with
# Owner (or the role set in docs/gcp-setup.md) on the project. Idempotent — safe
# to re-run; re-running with secret values set just adds new secret versions.
#
# It does NOT build or deploy anything (that's scripts/deploy_cloudrun.sh). It only
# ENABLES + PROVISIONS what a deploy needs:
#   1. Enables required Google APIs
#   2. Creates the Artifact Registry docker repo
#   3. Creates the GCS artifacts bucket
#   4. Creates 3 service accounts + grants the IAM they need
#   5. Mints a GCS SA key and stores it (base64) as the gcs-sa-key secret
#   6. Creates/populates the anthropic-api-key + alpha-redis-url secrets (if values given)
#
# Provide secret VALUES via env (recommended) or populate them yourself afterward:
#   ANTHROPIC_API_KEY=sk-ant-...   ALPHA_REDIS_URL=redis://...   bash scripts/gcp_bootstrap.sh
#
# Override defaults with: PROJECT=... REGION=... REPO=... BUCKET=... bash scripts/gcp_bootstrap.sh
set -euo pipefail

PROJECT="${PROJECT:-alpharesearch-500100}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-alpha}"
BUCKET="${BUCKET:-${PROJECT}-artifacts}"

# Runtime service accounts (created if absent).
ORCH_SA="alpha-orchestrator"   # Cloud Run service: FastAPI + runner
AGENT_SA="alpha-main-agent"    # Cloud Run Job: main agent
GCS_SA="alpha-gcs"             # writes artifacts; its key is the gcs-sa-key secret

SA_DOMAIN="${PROJECT}.iam.gserviceaccount.com"
ORCH_EMAIL="${ORCH_SA}@${SA_DOMAIN}"
AGENT_EMAIL="${AGENT_SA}@${SA_DOMAIN}"
GCS_EMAIL="${GCS_SA}@${SA_DOMAIN}"

echo "==> Project: ${PROJECT}  Region: ${REGION}  Bucket: gs://${BUCKET}  Repo: ${REPO}"
gcloud config set project "${PROJECT}" >/dev/null

echo "==> [1/6] Enable APIs"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com \
  cloudbuild.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  --project="${PROJECT}"

echo "==> [2/6] Artifact Registry repo (${REPO})"
gcloud artifacts repositories describe "${REPO}" --location="${REGION}" --project="${PROJECT}" \
  >/dev/null 2>&1 || \
  gcloud artifacts repositories create "${REPO}" --repository-format=docker \
    --location="${REGION}" --project="${PROJECT}"

echo "==> [3/6] GCS bucket (gs://${BUCKET})"
gcloud storage buckets describe "gs://${BUCKET}" --project="${PROJECT}" >/dev/null 2>&1 || \
  gcloud storage buckets create "gs://${BUCKET}" --project="${PROJECT}" --location="${REGION}"

echo "==> [4/6] Service accounts + IAM"
_ensure_sa() {  # name display
  gcloud iam service-accounts describe "${1}@${SA_DOMAIN}" --project="${PROJECT}" >/dev/null 2>&1 \
    || gcloud iam service-accounts create "${1}" --display-name="${2}" --project="${PROJECT}"
}
_ensure_sa "${ORCH_SA}"  "AlphaResearch orchestrator (API + runner)"
_ensure_sa "${AGENT_SA}" "AlphaResearch main-agent job"
_ensure_sa "${GCS_SA}"   "AlphaResearch GCS artifact writer"

_bind_project() {  # member role
  gcloud projects add-iam-policy-binding "${PROJECT}" \
    --member="serviceAccount:${1}" --role="${2}" --condition=None >/dev/null
}
# Orchestrator: trigger Cloud Run Jobs + read secrets + act-as the agent SA.
_bind_project "${ORCH_EMAIL}" "roles/run.developer"
_bind_project "${ORCH_EMAIL}" "roles/secretmanager.secretAccessor"
gcloud iam service-accounts add-iam-policy-binding "${AGENT_EMAIL}" --project="${PROJECT}" \
  --member="serviceAccount:${ORCH_EMAIL}" --role="roles/iam.serviceAccountUser" >/dev/null
# Main-agent job: read secrets (ANTHROPIC_API_KEY).
_bind_project "${AGENT_EMAIL}" "roles/secretmanager.secretAccessor"
# GCS writer: object admin on the artifacts bucket.
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" --project="${PROJECT}" \
  --member="serviceAccount:${GCS_EMAIL}" --role="roles/storage.objectAdmin" >/dev/null

echo "==> [5/6] Mint GCS SA key -> base64 for the gcs-sa-key secret"
KEYFILE="${GCS_SA_KEY_FILE:-}"
_CLEANUP_KEY=""
if [ -z "${KEYFILE}" ]; then
  KEYFILE="$(mktemp)"; _CLEANUP_KEY="${KEYFILE}"
  gcloud iam service-accounts keys create "${KEYFILE}" --iam-account="${GCS_EMAIL}" \
    --project="${PROJECT}"
fi
GCS_KEY_B64="$(base64 < "${KEYFILE}" | tr -d '\n')"
[ -n "${_CLEANUP_KEY}" ] && rm -f "${_CLEANUP_KEY}"

echo "==> [6/6] Secrets"
_ensure_secret() {  # name value
  gcloud secrets describe "${1}" --project="${PROJECT}" >/dev/null 2>&1 \
    || gcloud secrets create "${1}" --replication-policy=automatic --project="${PROJECT}"
  printf '%s' "${2}" | gcloud secrets versions add "${1}" --data-file=- --project="${PROJECT}" >/dev/null
  echo "    secret ${1}: version added"
}
_ensure_secret gcs-sa-key "${GCS_KEY_B64}"
if [ -n "${ANTHROPIC_API_KEY:-}" ]; then _ensure_secret anthropic-api-key "${ANTHROPIC_API_KEY}";
  else echo "    ! anthropic-api-key NOT set — export ANTHROPIC_API_KEY and re-run, or: gcloud secrets create anthropic-api-key --data-file=-"; fi
if [ -n "${ALPHA_REDIS_URL:-}" ]; then _ensure_secret alpha-redis-url "${ALPHA_REDIS_URL}";
  else echo "    ! alpha-redis-url NOT set — export ALPHA_REDIS_URL and re-run, or: gcloud secrets create alpha-redis-url --data-file=-"; fi

cat <<EOF

==> GCP bootstrap complete.
    Service accounts:
      orchestrator : ${ORCH_EMAIL}
      main-agent   : ${AGENT_EMAIL}
      gcs-writer   : ${GCS_EMAIL}
    Bucket: gs://${BUCKET}   Repo: ${REGION}-docker.pkg.dev/${PROJECT}/${REPO}

    Next:
      1) Ensure secrets anthropic-api-key + alpha-redis-url have values (see warnings above).
      2) bash scripts/deploy_cloudrun.sh          # build + deploy the service + main-agent Job
      3) modal deploy infra/modal_app.py          # deploy the sub_agent (see docs/gcp-setup.md)
    See docs/gcp-setup.md for the full runbook + the sub-agent volume-bridge caveat.
EOF
