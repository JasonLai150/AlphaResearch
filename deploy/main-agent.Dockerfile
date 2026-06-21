# Main-agent — Claude Code CLI research-director container.
#
# Boots `claude --dangerously-skip-permissions` rooted in /workspace, which is
# the contents of agent/main-agent/ (CLAUDE.md, .claude/settings.json + hooks,
# skills/, scripts/dispatch_subagent.py + scripts/schemas.py). The CLI session
# writes ./.dispatched/<job_id>.json records that an external runner picks up
# to spawn sub-agent containers.
#
# What's in this image (and only this):
#   - Linux + ca-certificates
#   - Python 3.12 + pydantic        — dispatch script + PreToolUse hook
#   - Node.js 22 + @anthropic-ai/claude-code  — the entrypoint
#   - The agent/main-agent/ workspace
#
# What's NOT in this image (deliberately):
#   - infra/ + orchestrator/        — different services, different deploys
#   - claude-agent-sdk (Python)     — old SDK-loop architecture, deprecated
#   - the ML / RL stack             — main-agent decomposes + dispatches; it does not train
#
# Build:  docker build -f deploy/main-agent.Dockerfile -t alpha-main-agent .
# Run:
#   docker run --rm -it -e ANTHROPIC_API_KEY=sk-ant-... \
#     -v "$(pwd)/.dispatched:/workspace/.dispatched" \
#     alpha-main-agent

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive \
    UV_HTTP_TIMEOUT=300

# Node 22 from NodeSource (Claude Code CLI requires Node >= 18). curl + gnupg
# are needed only to add the apt repo; purge them after to keep the image lean.
# Acquire::Retries + curl --retry harden the build against flaky/congested networks
# (apt mirrors and nodesource can drop mid-pull).
RUN apt-get -o Acquire::Retries=8 update \
    && apt-get -o Acquire::Retries=8 install -y --no-install-recommends \
        curl ca-certificates gnupg \
    && curl -fsSL --retry 8 --retry-delay 2 --retry-connrefused \
        https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get -o Acquire::Retries=8 install -y --no-install-recommends nodejs \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI = the actual entrypoint. `@latest` is intentional during P0;
# pin once we have a known-good version (see the bundled-CLI version in
# claude-agent-sdk for a reference: 2.1.x at the time of writing).
RUN npm install -g --fetch-retries=8 --fetch-retry-mintimeout=20000 \
        @anthropic-ai/claude-code@latest

# Single Python dep: pydantic. The dispatch script and PreToolUse hook both
# import scripts/schemas.py which uses pydantic — that's it.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
RUN uv pip install --system --no-cache "pydantic>=2.9"

WORKDIR /workspace
COPY agent/main-agent/ ./

# `claude --dangerously-skip-permissions` refuses to run as root → run as a non-root
# user. The workspace + the user's HOME (~/.claude lives there) must be writable.
RUN mkdir -p ./.dispatched ./meta-planning \
    && useradd -m -u 1000 agent \
    && chown -R agent:agent /workspace /home/agent
USER agent
ENV HOME=/home/agent

# Headless launcher: Cloud Run Jobs have no TTY, so we can't use the interactive
# `claude` REPL. launch.py fetches the goal from GET /internal/bootstrap and execs
# `claude -p`. ANTHROPIC_API_KEY + ALPHA_INTERNAL_{TOKEN,RUNNER_URL} MUST be set at run time.
ENTRYPOINT ["python3", "launch.py"]
