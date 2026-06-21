# AlphaResearch — Build Plan

Automated research platform: a Claude Agent SDK orchestrator that recursively
dispatches research sub-agents, each running in its own Modal sandbox, exploring
strategies in parallel and reporting results up to a single human interface.

---

## 1. North Star

- **One human interface.** The user talks only to the depth-0 (main) agent over SSE.
- **Recursive decomposition.** Any agent can break its problem into sub-problems and
  spawn sub-agents to solve them — sub-agents can do the same, all the way down.
- **Isolated compute.** Every sub-agent lives in its own containerized Modal VM with
  real sim deps (envpool, MuJoCo, minigrid).
- **Summaries up.** Agent→agent communication is unidirectional: a parent ingests only
  its children's final summaries. Raw logs/metrics stream separately to the UI.
- **Bounded compute.** A shared, decrementing budget governs the whole agent tree —
  the seed of the future compute-allocation system.

## 2. Core Principle — Self-Similar Agent Runtime

There is **one** agent program, `run_agent(job_id)`, run at every depth. The "main
agent" is just the job at depth 0 that has a user attached. A sub-agent spawning a
sub-agent is the identical code path to the main agent spawning a sub-agent.

```
run_agent(job_id):
    goal, params, depth, session_id = load(job_id)
    agent = ClaudeAgentSDK(tools=[dispatch_job, report_progress, query_children, finalize])
    run loop until goal addressed
    finalize -> write runs(summary, metrics) + artifacts   # flows UP to parent
```

| | Depth 0 (main) | Depth ≥1 (sub) |
|---|---|---|
| Runs in | Cloud Run worker | Modal function |
| Output | Redis Stream → SSE → user | Redis Stream (`events`/`runs`) → parent |
| Goal from | user message | parent's `dispatch_job` call |

Everything else is shared. Recursion = lifting a `max_depth` flag, not a rewrite.

## 2.5 Infra ↔ Research-Loop Boundary (build infra first, iterate loop later)

The build splits into two layers with a **stable contract** between them. Lock the
**infra layer** for P0; the **research-loop layer** sits above it and can be rewritten
freely (tree vs portfolio/ledger/synthesis, coordination, dedup-or-not) **without touching
infra**, as long as it only goes through the seam below.

```
┌─ Research-loop layer (SWAPPABLE) ─ prompts, roles, coordination, decomposition, synthesis ┐
│                         ▲ only calls the store/dispatch API, never Redis/GCS/Modal directly │
├─ Contract seam ─ store client + dispatch(kind,payload) + typed schemas ─────────────────────┤
│                                                                                              │
└─ Infra layer (LOCKED for P0) ─ Redis state, Streams/SSE, Modal spawn, GCS, Cloud Run ───────┘
```

Four infra deliverables make this seam real:

1. **`store` client layer** — *all* infra ops behind one module: `create_job`, `emit_event`,
   `write_run`, `decr_budget`, `put_artifact`, `get_children`, `read_state`. Loop code never
   touches Redis/GCS/Modal directly. This is the seam that makes "infra first" hold.
2. **Generic `dispatch(kind, payload)`** — `job.kind ∈ {agent, experiment}`; one primitive
   launches either an agentic sub-agent or a non-agentic compute job. Keeps infra neutral to
   whatever coordination model the loop later uses.
3. **Typed contracts** — `DispatchPayload`, `RunResult`, `EventEnvelope` as versioned pydantic
   models in one place. The stable API between the swappable loop and the fixed infra.
4. **`DISPATCH_BACKEND=local|modal` switch** — a stub backend runs `experiment` jobs in-process
   so the whole tree can be exercised locally against Redis, without redeploy/cold-start. Fast
   loop iteration is an infra feature.

> **Swappable, not fixed:** the "summaries-up / `query_children`" coordination below (§1, §2,
> §5) is a **P0 placeholder**, not infra. With the seam in place, changing it is a loop-layer
> edit above the line — no infra surgery.

## 3. Architecture

```
                         ┌──────────────── GCP ────────────────┐
User ──SSE──► Cloud Run (Next.js)                              │
                │                                              │
                └─SSE─► Cloud Run (FastAPI API)  ◄── XREAD ── Redis Streams (events bus)
                            │ enqueue session                       ▲   ▲
                            ▼                                       │   │ XADD
                   Cloud Run (orchestrator worker)                 │   │
                       run_agent (depth 0) ──────────────publishes─┘   │
                            │  tool calls                              │
                            ├─ dispatch_job ─► Modal.spawn(run_agent, child_id) [depth 1]
                            │                       │ (can dispatch_job → depth 2)
                            │                       └─ XADD events / runs / artifact-meta
                            └─ runner ◄──────────────────────────────┘
                         └──────────────────────────────────────┘
Redis (Redis Cloud)  ← state: sessions/jobs/runs (JSON), events+queue (Streams), budget (counters)
GCS                  ← artifact blobs (plots/checkpoints); URLs stored in Redis
```

### Tech stack
| Layer | Choice |
|---|---|
| Agent runtime | Claude Agent SDK (Python) |
| Sub-agent compute | Modal (`function.spawn`, GPU on demand, prebaked image) |
| Experiment code (P0) | **Prebaked** envs/simulators/trainers; agent selects + parameterizes |
| Experiment code (end goal) | Agent-authored `ExperimentSpec` materialized in a Modal Sandbox |
| Backend/API | FastAPI + SSE, on **Cloud Run** |
| State / DB | **Redis (Redis Cloud)** — JSON docs, Streams (events + queue), atomic counters (budget) |
| Blob storage | **Google Cloud Storage** (plots, checkpoints) |
| Hosting | **GCP**: Cloud Run (frontend, API, worker), Secret Manager, Artifact Registry |
| Frontend | Next.js + Tailwind, Recharts for metrics, inline `<img>` for plots |

> **Redis Cloud, not Memorystore:** use Redis Inc's managed **Redis Cloud** (runs on GCP)
> for sponsor-prize eligibility + Redis Stack features (JSON, Streams, Search). Memorystore
> is Google's Redis and likely won't count toward the Redis sponsor prize.
>
> **Why Redis is the backbone (not just a sponsor checkbox):** Streams = the cross-sub-agent
> SSE fan-in bus with built-in monotonic IDs that map 1:1 to SSE `Last-Event-ID`; atomic
> `DECRBY` = the recursion budget; Lists/Streams = the main-agent job queue; JSON = entities.
> One product covers four architectural needs.

## 4. Data Model — Redis (recursive by construction)

Redis Stack keyspace (use RedisJSON for docs, Streams for events/queue, plain ints for
atomic budget; optional RediSearch index on jobs for tree queries).

```
# Entities (RedisJSON)
session:{sid}            -> { user_id, goal, status, created_at }
session:{sid}:budget     -> INT (atomic; DECRBY on dispatch, reject if < 0)
job:{jid}                -> { session_id, parent_job_id|null, depth, kind, strategy,
                             params, modal_call_id, gpu, status }
                            # kind: agent|experiment ; status: pending|running|done|failed
run:{jid}                -> { status, summary, metrics }            # final result, flows UP
artifact:{aid}           -> { job_id, kind, gcs_url, caption }      # blob lives in GCS

# Relationships (Sets)
session:{sid}:jobs       -> SET of jids
job:{jid}:children       -> SET of child jids                       # the tree

# Streams
session:{sid}:events     -> XADD { job_id, parent_job_id, depth, type, payload }
                            # type: log|metric|status|spawn|artifact|summary
                            # entry ID is monotonic ts-seq → used directly as SSE Last-Event-ID
sessions:queue           -> XADD { session_id } ; worker consumer-group XREADGROUP
```

- **Budget** is a first-class atomic key: `DECRBY session:{sid}:budget <cost>` returns the
  remaining balance in one round-trip; negative → `dispatch_job` refuses and tells the agent
  to wrap up. No race, no transaction needed.
- **Events** are a Stream per session: every job at every depth `XADD`s; the SSE endpoint
  `XREAD BLOCK`s. Stream entry IDs are monotonic, so replay/reconnect is just
  `XREAD` from the client's `Last-Event-ID`.
- `parent_job_id` + `depth` + `session_id` are all the structure recursion needs.

## 5. Two Communication Channels (do not conflate)

1. **Agent→agent = summaries up.** `query_children` reads child `runs.summary` only.
   Keeps token usage bounded as the tree deepens. *(P0 placeholder coordination — a
   research-loop choice, swappable above the seam per §2.5, not infra.)*
2. **UI observability = session firehose.** Every job at every depth writes `events`
   tagged with `session_id`/`job_id`/`parent_job_id`. The frontend subscribes to the
   whole session and renders the **live agent tree** (nodes=jobs, edges=parent_job_id).

### Streaming / SSE across sub-agents
Sub-agents are remote/isolated (Modal containers) — they **cannot hold an SSE socket to
the browser**. So streaming "across sub-agents" is a fan-in: every agent publishes to a
shared bus; one **runner per session** multiplexes that bus into the single SSE stream
the user holds.

```
depth-0 agent (Cloud Run worker) ──XADD──┐
depth-1/2 sandboxes (Modal) ──────XADD──► session:{sid}:events (Redis Stream)
                                              │ XREAD BLOCK
                                              └─► Cloud Run API ──SSE──► browser
                                                                    (demux by job_id → cards/tree)
```

- **Bus = `session:{sid}:events` Redis Stream.** Every agent at every depth (including
  depth-0) `XADD`s to it. This decouples the agent from the request: the **SSE endpoint is a
  pure `XREAD BLOCK` tailer** and doesn't host the agent — which is what makes Cloud Run viable
  (the long-running agent is a separate worker; the API instance just streams the Stream).
- **All depths uniform.** Because depth-0 also publishes to the Stream rather than streaming
  in-process, the bus treats every node identically — *more* self-similar than the original
  in-process design.
- **Fidelity tiers:** durable events (status/metric/artifact/summary/spawn) → the Stream.
  Optional live token deltas → a separate Redis Pub/Sub channel (post-P0). For P0, sub-agents
  flush text in small chunks as `log` events — "live" feel, one bus.
- **Envelope:** every SSE message carries `session_id`/`job_id`/`parent_job_id`/`depth`/
  `type`/`payload`; client routes to the right card and builds the tree.
- **Replay/reconnect:** Stream entry IDs are monotonic → the client's `Last-Event-ID` is just
  an `XREAD` start point; a late/refreshed client rebuilds the whole tree from history.

## 6. Recursion Guardrails (= compute-allocation v0)

- `max_depth` — hard recursion stop (P0: 1, flip to 2 once depth-1 is stable).
- `max_fanout` — max children per node.
- `session_budget` — shared Redis counter (`session:{sid}:budget`); `dispatch_job` runs a
  single atomic `DECRBY` before every `spawn()`; result < 0 → "no budget, wrap up."
  This is the exact hook the future GPU-hour/priority allocator grows into.

---

## 7. P0 Prototype — Build Order (≈48h)

Goal: depth-0 agent spins up 2–3 Modal sandboxes exploring different params, each runs
a real experiment, summaries flow back, results + artifacts render in the chat UI.

> **Scope decision (P0):** experiment code is **prebaked** into the Modal image — a small
> registry of envs/simulators/trainers (envpool/MuJoCo/minigrid). The agent's job is to
> **select an env + trainer and choose params/strategy**, not to author novel simulation
> code. This removes the biggest stability risk for the 48h demo while keeping the full
> orchestration + recursion story intact. The dynamic, agent-authored path is documented
> in §8 as the end-goal extension and does not require redesign.

### Phase 0 — Setup (3–4h)
- [ ] Repo skeleton: `/agent /orchestrator /infra /web`.
- [ ] Modal account + `modal token`; **Redis Cloud** instance + URL; **GCP project**, GCS
      bucket, Secret Manager entries; keys in `.env`.
- [ ] `infra/redis_keys.md` (keyspace from §4); `infra/modal_app.py` image builds with
      `envpool`, `mujoco`, `minigrid`, `claude-agent-sdk`, **+ a prebaked simulator/trainer
      registry** (e.g. `envs.py` listing selectable envs + a PPO/SAC trainer entrypoint).
- [ ] Smoke test: a trivial Modal function `XADD`s one event to a Redis Stream; a local
      `XREAD` sees it. (Modal → Redis Cloud network reachability confirmed early.)

### Phase 1 — Infra seam + self-similar runtime, depth-0 only (10–12h)
- [ ] **`infra/store.py` (the contract seam):** wrap *all* Redis/GCS ops — `create_job`,
      `emit_event`, `write_run`, `decr_budget`, `put_artifact`, `get_children`, `read_state`.
      Loop/agent code calls only this, never Redis/GCS directly.
- [ ] **`infra/schemas.py`:** pydantic `DispatchPayload`, `RunResult`, `EventEnvelope`
      (versioned). The stable API between loop layer and infra.
- [ ] `agent/run_agent.py` + `agent/tools.py` (thin tools over `store`: dispatch_job,
      report_progress, query_children, finalize). Tools are loop-layer; `store` is infra.
- [ ] Run depth-0 in a plain Python script (no UI yet); `report_progress` + `finalize`
      against a hardcoded goal. Verify keys + Stream entries in Redis.

### Phase 2 — Generic dispatch + Modal, depth-1 (10–12h)  ← the hard part
- [ ] **Generic `dispatch(kind, payload)`** in `store`/infra: `job.kind ∈ {agent, experiment}`;
      writes child `job:{jid}` JSON, `DECRBY` budget, launches via the selected backend.
- [ ] **`DISPATCH_BACKEND=local|modal` switch:** `local` runs `experiment` jobs in-process
      (stub) for fast iteration; `modal` does `modal_fn.spawn(child_id)`. Same payload/result.
- [ ] An `agent`-kind job calls the **same** `run_agent(child_id)`; an `experiment`-kind job
      runs the prebaked env/trainer (no LLM).
- [ ] Child **selects a prebaked env + trainer and runs it with the chosen params**
      (envpool rollout / short train), uploads a matplotlib plot to **GCS** → writes
      `artifact:{aid}` (gcs_url) → writes `run:{jid}` summary. No dynamic code authoring in P0.
- [ ] `query_children` aggregates child summaries back into the parent.
      *(P0 placeholder coordination — swappable above the seam; see §2.5.)*
- [ ] **Milestone: depth-0 → 2–3 depth-1 sandboxes → results back.** Demo-able.

### Phase 3 — SSE backend + worker (6–8h)
- [ ] FastAPI API service: `POST /sessions` → `XADD sessions:queue` + create `session:{sid}`;
      `GET /sessions/{id}/stream` → `XREAD BLOCK session:{sid}:events`, emit SSE with the
      `session_id`/`job_id`/`parent_job_id` envelope; `Last-Event-ID` → `XREAD` start id.
- [ ] Orchestrator worker: `XREADGROUP sessions:queue` → runs depth-0 `run_agent`, which
      publishes to the events Stream like every other node (decoupled from the HTTP request).
- [ ] Runner duty: reconcile Modal handles (done/failed) into `job:{jid}.status` + a `status`
      event, so the UI sees terminal states even if a sandbox dies mid-run.

### Phase 4 — Frontend (8–10h)
- [ ] Next.js chat column consuming SSE.
- [ ] Live **agent-tree panel**: one card per job (status pill, metric sparkline from
      `metric` events, log tail). 2–3 cards updating in parallel.
- [ ] Inline artifact rendering (plots) + Recharts metric charts. Final results message
      links to each card.

### Phase 5 — Polish & flip recursion (4–6h)
- [ ] Set `max_depth=2`, run one deep tree, confirm tree view + budget hold.
- [ ] Error handling: failed Modal job → `status=failed` surfaces in UI, parent continues.
- [ ] Demo script + seed goal that reliably produces a good-looking tree.

### Phase 6 — Deploy to GCP (4–5h, can overlap Phase 4–5)
- [ ] Dockerfiles for **API**, **worker**, **web**; push to **Artifact Registry**.
- [ ] Deploy three **Cloud Run** services: `web` (Next.js), `api` (FastAPI SSE), `worker`
      (orchestrator). `worker` + `api`: CPU-always-allocated, `min-instances=1` (keep the
      Stream consumer + blocking reads alive); enable response streaming for SSE.
- [ ] Secrets via **Secret Manager** → mounted as env (`ANTHROPIC_API_KEY`, `REDIS_URL`,
      Modal tokens, GCS creds). Same secrets injected into Modal as `modal.Secret`.
- [ ] Redis Cloud reachable from Cloud Run **and** Modal (TLS + auth on the public endpoint).
- [ ] GCS bucket: signed URLs (or public-read for demo) so the browser can load plots.
- [ ] Smoke test the deployed loop end-to-end before demo day.

> **Hackathon shortcut:** if three services is too much, collapse `api`+`worker` into one
> Cloud Run service that runs `run_agent` as an asyncio background task on session start and
> still publishes to / reads from the Redis Stream. Same code, fewer deploys.

### P0 cutlines (drop in this order if time-constrained)
1. Depth-2 (keep `max_depth=1`).
2. Live metric sparklines (show final charts only).
3. GPU jobs (CPU-only envpool is plenty).
4. Multi-service split (use the single-service shortcut above).

---

## 8. Extension to End Goal

Each item builds on a P0 primitive — no rewrites.

### A. Deeper / wider recursion
- Lift `max_depth`/`max_fanout`; add cycle/duplicate-work detection across the tree.
- Move depth-0 into Modal too; backend becomes a pure tailer → fully uniform runtime.

### B. Compute allocation (grows from `session_budget`)
- Replace flat credits with **GPU-hours + priority weights** per node.
- Scheduler: concurrency semaphore + budget check becomes a real queue with
  per-session/per-user quotas and preemption of low-value branches.
- Cost-aware planning: agent estimates ROI of a sub-problem before spending budget.

### C. Richer sandboxes
- Prebaked, versioned images + Modal Volumes / snapshots so deps aren't reinstalled.
- Per-job resource requests (`gpu`, `cpu`, `mem`) threaded through `dispatch_job`
  (param already exists in P0).
- Datasets/checkpoints persisted to Storage; warm-start from a parent's checkpoint.

### D. Research quality
- Skills/tools for the agent: literature web-search, hypothesis tracking, experiment
  registry, automatic ablations.
- Result verification: a critic sub-agent re-checks claims before they flow up.
- Long-horizon memory: a project/experiment DB the agent queries across sessions.

### E. Observability & control
- Full agent-tree timeline with replay; per-node token/cost accounting.
- Human-in-the-loop checkpoints: pause a branch, inject guidance, resume.
- (Optional, later) limited downward messaging for steering long-running children —
  kept out of P0 by design to preserve the simple unidirectional model.

### F. Reliability
- Idempotent jobs + retries; orphaned-sandbox reaper.
- Structured run/result schema with typed metrics for cross-experiment comparison.

### G. Prebaked → agent-authored experiments (general autoresearch)
The P0 agent picks from a prebaked env/trainer registry. The end goal is the agent
**authoring the experiment** when simulator/trainer/tests/dataset/evals are decided in
conversation. This is an extension, not a redesign:
- Introduce an `ExperimentSpec { simulator, trainer, dataset, evals, env, resources }`.
- Add a `run_experiment(spec)` tool that opens a **Modal Sandbox** on the prebaked base
  image, `exec`-installs the long-tail packages, runs agent-authored code, captures
  metrics/artifacts. (Verified Modal capability: dynamic code + dynamic `pip install`
  + runtime GPU/image specs.)
- Design constraints to honor: prebake/cache the common 90% (cold-start), **mandatory
  checkpoint→Volume→resume** for >24h training, **persist the exact spec** (image def +
  code + dataset ref + seed) for reproducibility, and **budget-gate every spin-up**.
- Add a critic/verifier sub-agent to re-check agent-authored evals before summaries
  flow up.

---

## 9. Key Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Deep recursion explodes cost/time | `max_depth=1` until stable; hard `session_budget` |
| Modal image build slow/flaky | Build image early (Phase 0), pin versions |
| Modal-in-Modal spawn auth/lookup | Validate nested spawn in Phase 2 before UI work |
| Agent loops without finishing | `finalize` required + step cap + budget zero → wrap up |
| SSE/runner races on events | Redis Stream is append-only, monotonic IDs; SSE = `XREAD` tail |
| Modal can't reach Redis Cloud | Confirm public TLS endpoint + auth in Phase 0 smoke test |
| Cloud Run kills idle worker (Stream consumer dies) | CPU-always-allocated + `min-instances=1` |
| Redis as primary store durability | Redis Cloud persistence (AOF); blobs in GCS, not Redis |

## 10. Setup Checklist

- [ ] `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`
- [ ] `REDIS_URL` (Redis Cloud, TLS) — reachable from Cloud Run **and** Modal
- [ ] `ANTHROPIC_API_KEY`
- [ ] `GCP_PROJECT`, `GCS_BUCKET`, GCS service-account creds
- [ ] GCP: Cloud Run + Artifact Registry + Secret Manager enabled
- [ ] Secrets mirrored into Modal as `modal.Secret` (Redis URL, GCS creds, Anthropic key)
- [ ] `modal deploy infra/modal_app.py` (so `run_agent` is addressable for nested spawn)
- [ ] `DISPATCH_BACKEND` = `local` (dev, in-process stub) | `modal` (deployed)
