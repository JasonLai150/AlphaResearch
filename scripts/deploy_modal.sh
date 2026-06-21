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

# Agent OTEL (Layer A): when OTEL_EXPORTER_OTLP_ENDPOINT is set in .env, bake Claude
# Code's native-telemetry config into the secret. sub_agent() inherits these via the
# Modal function's os.environ and copies them into the agent subprocess, so the
# sub-agent's OTEL traces export to Sentry. (Per-exec TRACEPARENT rides as a call arg.)
OTEL_SECRET_ARGS=()
if [ -n "${OTEL_EXPORTER_OTLP_ENDPOINT:-}" ]; then
  OTEL_SECRET_ARGS=(
    ALPHA_AGENT_OTEL_ENABLED="true"
    CLAUDE_CODE_ENABLE_TELEMETRY="1"
    CLAUDE_CODE_ENHANCED_TELEMETRY_BETA="1"
    OTEL_TRACES_EXPORTER="otlp"
    OTEL_LOGS_EXPORTER="otlp"
    OTEL_EXPORTER_OTLP_PROTOCOL="http/protobuf"
    OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT}"
    OTEL_EXPORTER_OTLP_HEADERS="${OTEL_EXPORTER_OTLP_HEADERS:-}"
    OTEL_LOG_USER_PROMPTS="true"
    OTEL_LOG_TOOL_DETAILS="true"
    OTEL_LOG_TOOL_CONTENT="true"
  )
fi

uv run modal secret create alpha-secrets --force \
  ALPHA_REDIS_URL="$ALPHA_REDIS_URL" \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  ALPHA_DISPATCH_BACKEND="modal" \
  ALPHA_GCS_BUCKET="$ALPHA_GCS_BUCKET" \
  GOOGLE_APPLICATION_CREDENTIALS_B64="$GCS_B64" \
  SENTRY_DSN="${SENTRY_DSN:-}" \
  SENTRY_ENVIRONMENT="cloud" \
  ${OTEL_SECRET_ARGS[@]+"${OTEL_SECRET_ARGS[@]}"}

echo "==> deploying infra/modal_app.py"
uv run modal deploy infra/modal_app.py

echo "==> done. Flip .env: ALPHA_DISPATCH_BACKEND=modal, then re-run scripts/smoke_infra.py"
