# API + runner image — the Cloud Run *service* entrypoint.
#
# Hosts orchestrator/api.py (FastAPI + SSE + internal API) and the runner's
# asyncio loops in one process. The Modal SDK lives here (the runner spawns
# sub-agent Modal Functions); google-cloud-run lives here (the runner triggers
# the main-agent Cloud Run Job); google-cloud-storage lives here (artifact upload).
#
# Deliberately EXCLUDES the agent images (deploy/main-agent.Dockerfile,
# deploy/sub-agent.Dockerfile) — those are separate build+deploy targets.
#
# Build:  docker buildx build --platform=linux/amd64 -f deploy/api.Dockerfile -t alpha-api .

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    ALPHA_VOLUME_ROOT=/mnt/alpha-volumes

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Install dependencies first (cache layer), then the source.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY infra ./infra
COPY orchestrator ./orchestrator
COPY runner ./runner

RUN mkdir -p ${ALPHA_VOLUME_ROOT}

EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn orchestrator.api:app --host 0.0.0.0 --port ${PORT:-8080}"]
