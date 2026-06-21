# Sub-agent — Claude Code CLI experimenter container.
#
# Boots `claude --dangerously-skip-permissions` rooted in /workspace = contents
# of agent/sub-agent/ (CLAUDE.md, .claude/settings.json, skills/). The runner
# mounts the per-session Modal Volume at /workspace/.dispatched and injects
# ALPHA_JOB_ID + the per-session token; the agent reads its dispatch record from
# /workspace/.dispatched/${ALPHA_JOB_ID}.json and writes /workspace/result.json,
# which the Stop hook publishes into the volume (see agent/sub-agent/CLAUDE.md).
#
# Inside Bash sessions the agent runs real RL training, so the ML stack is
# baked in. EnvPool ships only Linux x86_64 manylinux wheels and its last release
# (0.8.4) tops out at the cp311 ABI — there are NO cp312 wheels — hence
# python:3.11-slim-bookworm + --platform=linux/amd64.
#
# What's in this image:
#   - Linux + libgomp1/libstdc++6 (EnvPool .so dlopen targets) + ca-certificates
#   - Python 3.12 + pydantic + envpool + gymnasium + minigrid + numpy + matplotlib
#   - Node.js 22 + @anthropic-ai/claude-code  — the entrypoint
#   - The agent/sub-agent/ workspace
#
# What's NOT in this image (deliberately):
#   - infra/ + orchestrator/        — sub-agent only talks to its own filesystem
#   - claude-agent-sdk (Python)     — old SDK-loop architecture, deprecated
#
# Build:
#   docker buildx build --platform=linux/amd64 -f deploy/sub-agent.Dockerfile \
#     -t alpha-sub-agent .
# Run:
#   docker run --rm --platform=linux/amd64 \
#     -e ANTHROPIC_API_KEY=sk-ant-... \
#     -v /path/to/job.json:/workspace/job.json:ro \
#     -v /path/to/results:/workspace/artifacts \
#     alpha-sub-agent
#
# EnvPool sanity check (skips claude entirely):
#   docker run --rm --platform=linux/amd64 --entrypoint python3 alpha-sub-agent -c \
#     "import envpool; e=envpool.make('MiniGrid-Empty-8x8-v0', env_type='gymnasium', \
#      num_envs=64); e.reset(); print(e.step(e.action_space.sample().repeat(64))[0].shape)"

FROM --platform=linux/amd64 python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# System: Node + EnvPool runtime libs + TLS roots. libgomp1 + libstdc++6 cover
# the MiniGrid binding; the wheel ships its own gfootball/procgen libs so we
# don't need SDL2/Qt/GLEW for the MiniGrid path.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg \
        libgomp1 libstdc++6 \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code@latest

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# ML stack baked in — the agent's Bash sessions use python3 to train, evaluate,
# and write artifacts. envpool 0.8.4 has Linux x86_64 wheels for py 3.8–3.11 only.
# pydantic is here because /workspace/job.json mirrors ResearchPlan and the
# agent may want to (re-)validate inputs from Bash.
RUN uv pip install --system --no-cache \
        "pydantic>=2.9" \
        "envpool==0.8.4" \
        "gymnasium==1.3.0" \
        "minigrid==3.1.0" \
        "numpy" \
        "matplotlib"

WORKDIR /workspace
COPY agent/sub-agent/ ./

RUN mkdir -p ./artifacts

# claude refuses --dangerously-skip-permissions as root → non-root user (workspace +
# HOME writable). On Modal, sub_agent() also drops to this user via subprocess(user=).
RUN useradd -m -u 1000 agent \
    && chown -R agent:agent /workspace /home/agent
USER agent
ENV HOME=/home/agent

# Headless launcher (no TTY in the sandbox): builds the one-shot prompt from the
# dispatch record and execs `claude -p`. The Modal sub_agent function overrides this
# entrypoint but runs the same launch.py — keep them in sync.
ENTRYPOINT ["python3", "launch.py"]
