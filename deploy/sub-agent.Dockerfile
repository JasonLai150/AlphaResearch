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
# baked in. EnvPool ships Linux x86_64 manylinux wheels only — hence
# python:3.11-slim-bookworm + --platform=linux/amd64.
#
# What's in this image:
#   - Linux + libgomp1/libstdc++6 (EnvPool .so dlopen targets) + ca-certificates
#   - Python 3.11 + pydantic + envpool 1.2.5 (MiniGrid + MuJoCo + Atari + classic
#     control) + gymnasium + minigrid + numpy + matplotlib + wandb + Browserbase
#   - torch (CPU) + the prebaked PPO trainer (scripts/train_ppo.py)
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

# EnvPool ships linux/amd64 wheels, so the base must be amd64 even on arm64
# hosts. Pin it via a build ARG — a constant --platform value
# on FROM trips the BuildKit lint (FromPlatformFlagConstDisallowed); a variable
# does not, and the default keeps amd64 even when --platform isn't passed.
ARG ENVPOOL_PLATFORM=linux/amd64
FROM --platform=${ENVPOOL_PLATFORM} python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Sub-agents run on Haiku 4.5 — the fastest, cheapest tier — since they do many
# parallel one-shot experiment runs where speed/cost matter more than peak reasoning.
# launch.py passes this as `claude -p --model $ALPHA_MODEL`.
# (Note: Claude Code's "/fast mode" is an Opus-4.6+-only interactive feature, so it
# does not apply to Haiku; Haiku 4.5 IS the fast path here. Override per-run with
# ALPHA_MODEL if a sub-agent needs a stronger model.)
ENV ALPHA_MODEL=claude-haiku-4-5-20251001

# CPU-PPO tuning (perf levers 3 + 4), sized to the Modal cpu=8 budget:
#  - OMP/MKL/OPENBLAS thread caps: keep the torch learner from oversubscribing BLAS and
#    contending with envpool's env-stepping threads (small MiniGrid nets need few learner
#    threads; the cores are better spent stepping envs). (Lever 3)
#  - ALPHA_NUM_ENVS: default a high parallel-env count so envpool actually vectorizes —
#    sim throughput scales with parallel envs until cores saturate. The agent reads this
#    (CLAUDE.md) for `envpool.make(..., num_envs=$ALPHA_NUM_ENVS)`. (Lever 4)
ENV OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    OPENBLAS_NUM_THREADS=4 \
    ALPHA_NUM_ENVS=64

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

# Pinned to the claude-code `stable` channel (not @latest) for reproducible image
# builds — bump this deliberately. (`npm view @anthropic-ai/claude-code dist-tags`)
RUN npm install -g @anthropic-ai/claude-code@2.1.176

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# ML + monitoring stack in ONE layer (faster builds + better cache). The prebaked
# trainer scripts/train_ppo.py uses envpool (vectorized) + torch + wandb + matplotlib;
# tensorboard is dropped (train_ppo.py logs to wandb + writes matplotlib curves).
# pydantic is here because /workspace/.dispatched/<jid>.json mirrors ResearchPlan.
# envpool 1.2.x is the first line to ship the MiniGrid env family (DoorKey, Empty,
# FourRooms, BabyAI, ...) alongside Atari / MuJoCo / classic-control — cp311 manylinux
# x86_64 wheels; we stay on 3.11. wandb + Browserbase/Stagehand drive capture_wandb.py
# (playwright is only a CDP client to the REMOTE Browserbase browser — no local Chromium).
RUN uv pip install --system --no-cache \
        "pydantic>=2.9" \
        "envpool==1.2.5" \
        "gymnasium==1.3.0" \
        "minigrid==3.1.0" \
        "numpy" \
        "matplotlib" \
        "wandb" \
        "browserbase" \
        "playwright" \
        "stagehand"

# Torch (CPU-only wheel — no CUDA) is the PPO learner. Separate RUN + the PyTorch CPU
# index so we don't pull the multi-GB CUDA build.
RUN uv pip install --system --no-cache \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch"

WORKDIR /workspace
COPY agent/sub-agent/ ./

RUN mkdir -p ./artifacts

# claude refuses --dangerously-skip-permissions as root → create a non-root `agent`
# user (workspace + HOME writable). We do NOT set `USER agent` here: this image runs on
# Modal, whose harness runs as root and would break under a non-root USER; the sub_agent
# function drops to `agent` for the claude subprocess via subprocess(user="agent").
RUN useradd -m -u 1000 agent \
    && chown -R agent:agent /workspace /home/agent

# No ENTRYPOINT: Modal invokes launch.py from the sub_agent function with the right env
# (ALPHA_JOB_ID etc.). An ENTRYPOINT here fires at container boot with no args and crashes
# (see infra/modal_app.py .entrypoint([])). launch.py is the launcher; the function runs it.
