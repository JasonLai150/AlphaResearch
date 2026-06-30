#!/usr/bin/env bash
# Stage 3: create/refresh the alpha-secrets Modal secret from .env + the SA key,
# then deploy the Modal app so run_job is addressable (incl. nested spawn).
#
#   modal token new        # once, interactive
#   bash scripts/deploy_modal.sh
set -euo pipefail
cd "$(dirname "$0")/.."

# Load .env (ALPHA_REDIS_URL, ANTHROPIC_API_KEY, ALPHA_GCS_BUCKET)
set -a; source .env; set +a

: "${ALPHA_REDIS_URL:?set in .env}"
: "${ANTHROPIC_API_KEY:?set in .env}"
: "${ALPHA_GCS_BUCKET:?set in .env}"
test -f gcs-sa-key.json || { echo "gcs-sa-key.json missing"; exit 1; }

echo "==> creating Modal secret 'alpha-secrets'"
# SA key passed as single-line base64 — raw multi-line JSON hangs `modal secret create`.
GCS_B64="$(base64 < gcs-sa-key.json | tr -d '\n')"

uv run modal secret create alpha-secrets --force \
  ALPHA_REDIS_URL="$ALPHA_REDIS_URL" \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  ALPHA_DISPATCH_BACKEND="modal" \
  ALPHA_GCS_BUCKET="$ALPHA_GCS_BUCKET" \
  GOOGLE_APPLICATION_CREDENTIALS_B64="$GCS_B64"

echo "==> deploying infra/modal_app.py"
uv run modal deploy infra/modal_app.py

echo "==> warm-up + image smoke (imports torch+envpool in the real sub-agent image;"
echo "    catches a broken image now, not on the first chat; pre-pulls the image)"
uv run modal run infra/modal_app.py::warmup || echo "WARN: warmup failed — check the sub-agent image before demoing"

echo "==> done. Flip .env: ALPHA_DISPATCH_BACKEND=modal, then re-run scripts/smoke_infra.py"
