# AlphaResearch

Recursive automated-research platform: a single Claude Agent SDK orchestrator (the
"main agent") that the user talks to, which recursively dispatches research
sub-agents — each in its own Modal sandbox — to explore strategies in parallel and
report summaries back up. State, the event bus, the job queue, and the compute
budget all live in Redis; artifacts live in GCS.

Plan & tasks: `meta-planning/docs/plan.md`, `meta-planning/docs/tasks.md`; design
rationale: `meta-planning/docs/design.md`.

**Status:** cloud backplane (Redis Cloud + GCS + Modal) wired and verified end-to-end
via `scripts/smoke_modal.py`. Next: full agent loop over Modal, then the live web demo.

## Layout

```
agent/         self-similar run_agent + Claude Agent SDK tools (research-loop layer)
infra/         the LOCKED seam: store (Redis/GCS), schemas, dispatch, registry, modal_app
orchestrator/  FastAPI API (sessions + SSE), depth-0 worker, Modal runner
web/           Next.js chat + live agent-tree dashboard
scripts/       dev harnesses
deploy/        docker-compose.dev.yml, Cloud Run configs
```

The architecture is split by a stable seam (`infra/store.py` + `infra/dispatch.py`
+ `infra/schemas.py`): the research-loop layer (`agent/`) only ever calls that seam,
never Redis/GCS/Modal directly — so the loop can be rewritten without touching infra.

## Quickstart (local, no cloud)

```bash
# 1. deps (Python pinned to 3.12 via uv)
uv sync --extra dev

# 2. local Redis Stack (RedisJSON + Streams)
docker compose -f deploy/docker-compose.dev.yml up -d

# 3. configure
cp .env.example .env        # set ANTHROPIC_API_KEY; ALPHA_DISPATCH_BACKEND=local

# 4a. infra-only smoke (no API key needed) — exercises store + dispatch + experiment stub
uv run python scripts/smoke_infra.py

# 4b. full depth-0 agent loop (needs ANTHROPIC_API_KEY)
uv run python scripts/run_depth0.py "Improve PPO sample efficiency on MiniGrid-DoorKey-8x8"

# 5. API + SSE
uv run uvicorn orchestrator.api:app --reload --port 8080
#   POST /sessions {"goal": "..."}  ->  GET /sessions/{id}/stream  (SSE)
```

`DISPATCH_BACKEND=local` runs the whole tree in-process with synthetic experiment
stubs — fast iteration with only Redis up. Switch to `modal` once the Modal image is
built and credentials are set.

## Configuration: `.env` vs Modal secrets

Two runtimes, two config sources — they are **separate**:

- **`.env`** configures processes on your machine (orchestrator/API/worker, and
  `DISPATCH_BACKEND=local`). Loaded by `infra/config.py`.
- **The `alpha-secrets` Modal secret** is injected as env vars into the cloud Modal
  containers (depth ≥ 1 sub-agents / experiments). They never see your local `.env`.

A few values must exist in **both** places because each runtime reads its own source:

| value | local `.env` | Modal `alpha-secrets` |
|---|---|---|
| Redis URL | ✅ | ✅ |
| `ANTHROPIC_API_KEY` | ✅ | ✅ |
| GCS bucket / creds | ✅ | ✅ |
| Modal token | — (in `~/.modal.toml`) | — (ambient in Modal) |

> When `DISPATCH_BACKEND=modal`, set the Redis URL to your **Redis Cloud** endpoint
> (`rediss://…`) in **both** places — never `localhost`. The local orchestrator and the
> cloud sandboxes must share the same Redis. For pure local dev (`DISPATCH_BACKEND=local`)
> you don't need the Modal secret at all and `.env` keeps `localhost`.

## Modal setup (only for `DISPATCH_BACKEND=modal`)

```bash
modal token new                       # authenticate (writes ~/.modal.toml)

modal secret create alpha-secrets \
  ALPHA_REDIS_URL="rediss://default:<password>@<host>:<port>" \
  ANTHROPIC_API_KEY="sk-ant-..." \
  ALPHA_GCS_BUCKET="alpha-artifacts" \
  ALPHA_DISPATCH_BACKEND="modal"

modal deploy infra/modal_app.py       # makes run_job addressable (incl. nested spawn)
```

The secret name must be `alpha-secrets` (referenced in `infra/modal_app.py`). GCS uploads
need a service-account credential — use the Modal dashboard's Google Cloud secret template,
or leave `ALPHA_GCS_BUCKET` unset to fall back to local-disk artifacts while validating the
Modal compute path first.

## Frontend (`web/`)

The Next.js app talks to the FastAPI API over REST + SSE. For local development you
can run the API in **local-sim** mode (a scripted research run per session, no cloud
credentials) and point the web app at it:

```bash
# Terminal 1 — API in local-sim mode (no Cloud Run/Modal, no ANTHROPIC_API_KEY)
ALPHA_RUNNER_ENABLED=false ALPHA_LOCAL_SIM=true \
  uv run uvicorn orchestrator.api:app --port 8080

# Terminal 2 — Next.js dev server (http://localhost:3000)
cd web && npm run dev
```

Copy `web/.env.example` to `web/.env.local` first. With Clerk left unset the web app
runs keyless as a fixed "demo" user (see `web/lib/auth-config.ts`); the API similarly
stays in open dev mode while `ALPHA_CLERK_JWKS_URL` is unset.

## Production deploy

Deploy the API (Cloud Run / your host of choice), then configure the three boundaries —
the web → API URL, Clerk auth on both sides, and CORS:

1. **Point the web app at the deployed API.** Set `NEXT_PUBLIC_API_URL` in the web
   environment to the deployed API origin (e.g. `https://api.example.com`). It is
   inlined at build time (`web/lib/types.ts` reads `process.env.NEXT_PUBLIC_API_URL`),
   so set it before building the frontend.

2. **Enable Clerk.** Without these the app runs as the open "demo" user, so set them
   in production:
   - Web: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` + `CLERK_SECRET_KEY` (from the Clerk
     dashboard). Setting the publishable key flips `CLERK_ENABLED` on, requiring
     sign-in and sending a verified token to the API.
   - Backend: `ALPHA_CLERK_JWKS_URL` (e.g.
     `https://<subdomain>.clerk.accounts.dev/.well-known/jwks.json`) and
     `ALPHA_CLERK_ISSUER` (**required** whenever the JWKS URL is set — the API fails
     fast otherwise). `ALPHA_CLERK_AUDIENCE` is optional. Run `uv sync --extra auth`
     so the JWT-verification deps are present.

3. **Set CORS to the deployed web origin.** The API's allowed browser origins are
   env-driven via `ALPHA_CORS_ALLOW_ORIGINS` (backs `settings.cors_allow_origins` in
   `infra/config.py`; defaults to `["http://localhost:3000"]`). It is parsed as a JSON
   list, so set it to your deployed web origin(s):

   ```bash
   ALPHA_CORS_ALLOW_ORIGINS='["https://app.example.com"]'
   ```
