#!/usr/bin/env bash
# Run the API locally for frontend development: local-sim runner (no cloud creds) against
# the local redis-stack container. Overrides ALPHA_REDIS_URL to the local instance via
# env-var precedence, so your .env is never modified and its (possibly cloud/malformed)
# value is sidestepped.
#
#   bash scripts/dev_api_local.sh
#
# Pair with the frontend:  cd web && npm run dev   (http://localhost:3000)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Ensure local Redis (redis-stack: RedisJSON + Streams) is up.
if ! docker ps --filter name=alpha-redis --format '{{.Names}}' | grep -q alpha-redis; then
  echo "[dev] starting local redis-stack…"
  docker compose -f deploy/docker-compose.dev.yml up -d
fi

export ALPHA_REDIS_URL="redis://localhost:6379/0"
export ALPHA_LOCAL_SIM="true"
export ALPHA_RUNNER_ENABLED="false"
# Blank the GCS bucket so artifacts (e.g. local-sim's reward.svg) save to local disk
# (.artifacts/, served by the API) instead of requiring gcloud auth.
export ALPHA_GCS_BUCKET=""

echo "[dev] API → http://localhost:8080  (redis=local, local-sim=on, runner=off, artifacts=disk)"
exec uv run uvicorn orchestrator.api:app --reload --port 8080
