#!/usr/bin/env bash
# Idempotent Cloud Run deploy for the AlphaResearch backend.
#
# Builds + pushes two images (api service, main-agent job), deploys the API as a
# Cloud Run *service*, and creates/updates the main-agent Cloud Run *Job* that the
# runner triggers per chat. Sub-agents run on Modal (deploy separately via
# scripts/deploy_modal.sh + `modal deploy infra/modal_app.py`).
#
# PREREQ: run scripts/gcp_bootstrap.sh ONCE first (enables APIs, creates the AR repo,
# bucket, service accounts + IAM, and secrets). This script assumes that's done.
#
# Safe to re-run. Reads PROJECT/REGION/... from env or uses the defaults below.
set -euo pipefail

PROJECT="${PROJECT:-alpharesearch-500100}"
REGION="${REGION:-us-central1}"
REPO="${REPO:-alpha}"
BUCKET="${BUCKET:-${PROJECT}-artifacts}"
SERVICE="${SERVICE:-alpha-api}"
AGENT_JOB="${AGENT_JOB:-alpha-main-agent}"
# Runtime service accounts created by gcp_bootstrap.sh.
ORCH_SA="${ORCH_SA:-alpha-orchestrator@${PROJECT}.iam.gserviceaccount.com}"
AGENT_SA="${AGENT_SA:-alpha-main-agent@${PROJECT}.iam.gserviceaccount.com}"
TAG="${TAG:-v$(date +%Y%m%d-%H%M%S)}"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"
IMAGE_API="${REGISTRY}/api:${TAG}"
IMAGE_AGENT="${REGISTRY}/main-agent:${TAG}"

echo "==> Enable APIs"
gcloud services enable run.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com storage.googleapis.com cloudbuild.googleapis.com \
    --project="${PROJECT}"

echo "==> Ensure Artifact Registry repo"
gcloud artifacts repositories describe "${REPO}" --location="${REGION}" --project="${PROJECT}" \
    >/dev/null 2>&1 || \
    gcloud artifacts repositories create "${REPO}" --repository-format=docker \
        --location="${REGION}" --project="${PROJECT}"

echo "==> Ensure GCS bucket"
gcloud storage buckets describe "gs://${BUCKET}" --project="${PROJECT}" >/dev/null 2>&1 || \
    gcloud storage buckets create "gs://${BUCKET}" --project="${PROJECT}" --location="${REGION}"

echo "==> Check required secrets exist (create once, by hand)"
# modal-token-{id,secret}: the runner spawns sub-agent Modal Functions from Cloud Run,
# so it needs Modal API creds (no ~/.modal.toml in the container). Mint with
# `modal token new`, then push the values from ~/.modal.toml into these secrets.
for s in anthropic-api-key alpha-redis-url gcs-sa-key modal-token-id modal-token-secret; do
    gcloud secrets describe "${s}" --project="${PROJECT}" >/dev/null 2>&1 || {
        echo "ERROR: secret '${s}' missing. Create it: gcloud secrets create ${s} --data-file=-"
        exit 1
    }
done
# NOTE (SEV-4): there is NO shared alpha-internal-token secret. The runner mints a
# per-session ephemeral token and injects it into each agent execution at spawn.

echo "==> Build + push images"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker buildx build --platform=linux/amd64 -f deploy/api.Dockerfile -t "${IMAGE_API}" . --push
docker buildx build --platform=linux/amd64 -f deploy/main-agent.Dockerfile -t "${IMAGE_AGENT}" . --push

echo "==> Deploy Cloud Run service (orchestrator: API + runner)"
# max-instances stays at 1 for the MVP; the runner's Redis leader lease (SEV-2) makes
# it SAFE to raise later — only the lease holder runs the loops, so a rolling-deploy
# overlap never double-spawns.
gcloud run deploy "${SERVICE}" --image="${IMAGE_API}" --region="${REGION}" --project="${PROJECT}" \
    --service-account="${ORCH_SA}" \
    --allow-unauthenticated --min-instances=1 --max-instances=1 --no-cpu-throttling \
    --memory=1Gi --cpu=1 --port=8080 \
    --set-secrets="ANTHROPIC_API_KEY=anthropic-api-key:latest,\
ALPHA_REDIS_URL=alpha-redis-url:latest,\
GOOGLE_APPLICATION_CREDENTIALS_B64=gcs-sa-key:latest,\
MODAL_TOKEN_ID=modal-token-id:latest,\
MODAL_TOKEN_SECRET=modal-token-secret:latest" \
    --set-env-vars="ALPHA_GCS_BUCKET=${BUCKET},ALPHA_MODAL_APP_NAME=alpharesearch,\
ALPHA_GCP_PROJECT=${PROJECT},ALPHA_GCP_REGION=${REGION},ALPHA_MAIN_AGENT_JOB_NAME=${AGENT_JOB},\
ALPHA_RUNNER_ENABLED=true"

URL=$(gcloud run services describe "${SERVICE}" --region="${REGION}" --project="${PROJECT}" \
    --format='value(status.url)')
echo "==> Service URL: ${URL}"

# Point the runner at its own public URL (agents push telemetry/dispatch here).
gcloud run services update "${SERVICE}" --region="${REGION}" --project="${PROJECT}" \
    --update-env-vars="ALPHA_INTERNAL_RUNNER_URL=${URL}"

echo "==> Create/update main-agent Cloud Run Job"
# The per-session token (ALPHA_INTERNAL_TOKEN) is injected PER-EXECUTION by the runner
# (SEV-4) — never in the Job spec. The Job spec only needs the model key + runner URL.
gcloud run jobs describe "${AGENT_JOB}" --region="${REGION}" --project="${PROJECT}" \
    >/dev/null 2>&1 && CMD=update || CMD=create
gcloud run jobs "${CMD}" "${AGENT_JOB}" \
    --image="${IMAGE_AGENT}" --region="${REGION}" --project="${PROJECT}" \
    --service-account="${AGENT_SA}" \
    --task-timeout=4h --max-retries=0 --memory=2Gi --cpu=2 \
    --set-secrets="ANTHROPIC_API_KEY=anthropic-api-key:latest" \
    --set-env-vars="ALPHA_INTERNAL_RUNNER_URL=${URL}"

echo "==> Deployed."
echo "    Service:  ${URL}"
echo "    Smoke:    curl ${URL}/healthz"
echo "    Reminder: deploy sub-agents to Modal:  modal deploy infra/modal_app.py"
