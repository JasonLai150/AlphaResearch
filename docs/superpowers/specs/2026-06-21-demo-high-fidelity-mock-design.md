# Demo — High-Fidelity Mock of AlphaResearch

**Date:** 2026-06-21
**Status:** Approved design → ready for implementation plan
**Worktree:** `.claude/worktrees/demo-mock` (branch `worktree-demo-mock`)
**Home:** `demo/` (self-contained, runnable with one `pnpm dev`)

## 1. Goal

A high-fidelity, fully **mocked** version of the AlphaResearch website that runs with
**no backend, no auth provider, and no API keys**. It demonstrates the full product
experience — landing → sign-in → research chat with live streaming → drill-in
researcher inspector → autonomous loops — driven entirely by a **seeded, scripted,
semi-stochastic simulation engine**.

### Resolved product decisions

| Decision | Choice |
|---|---|
| Stream/content source | **Scripted stochastic only** — no API calls, seeded PRNG |
| Site scope | **Full-site clone** — landing, mock sign-in, all shell pages, chat, `/view`, autonomous |
| Control model | **Free interactive** — user types any goal; engine improvises a plausible run. No playback controls (no pause/scrub/speed) |
| Dummy server | **Next.js Route Handlers** in-app (no separate Python process) |
| Component reuse | **Copy** the real design system + components into `demo/` (self-contained) |
| Determinism | Seed = `hash(goal) + per-session nonce` → varies per session, replayable within a session. **No `Math.random`** anywhere |

## 2. Core principle — swap the *source*, not the *renderer*

The real app's data path is: FastAPI/Redis/Modal backend → SSE `EventEnvelope`
stream → `streamSession` fetch-SSE client → `session-reducer` → React components.

The demo replaces **only the event source**. Everything downstream is the real code,
copied verbatim: the SSE client, the reducer, the types, and the components. The
dummy server emits the exact same `EventEnvelope` wire format
(`log | metric | status | spawn | artifact | summary | error | token`), just paced
slowly and generated from the simulation engine. Same bytes in → identical UI out.
This is the fidelity guarantee.

### The wire contract (must match `web/lib/types.ts` / `infra/schemas.py`)

```ts
interface EventEnvelope {
  session_id: string; job_id: string; parent_job_id: string | null;
  depth: number; type: EventType; payload: Record<string, any>;
  ts: string; v: number;
}
type EventType = "log" | "metric" | "status" | "spawn" | "artifact" | "summary" | "error" | "token";
```

`token` events carry `{ msg_id, role, delta, tool_name? }` and drive the typewriter
caret. `metric` events carry `{ step, reward, ... }` (extended below). `spawn`,
`status`, `artifact`, `summary` mirror the existing reducer expectations in
`web/lib/session-reducer.ts` — the spec's acceptance test is that the copied reducer
folds the mock stream with zero changes.

## 3. Folder & app shape

```
demo/
  package.json                # standalone Next.js app (web's deps minus @clerk/*)
  next.config.mjs  tsconfig.json  postcss.config.mjs  vitest.config.ts
  app/
    layout.tsx  globals.css    # copied design system (Tailwind v4 tokens, Geist font)
    page.tsx                   # landing (mock of real landing-hero/nav)
    sign-in/page.tsx           # one-click "Enter demo" (fake auth)
    (shell)/
      layout.tsx               # app shell + sidebar nav
      overview/page.tsx
      projects/page.tsx
      autonomous/page.tsx      # NEW autonomous-loops section
      settings/page.tsx  integrations/page.tsx  account/page.tsx
    app/page.tsx               # the research chat (free-interactive)
    view/[jobId]/page.tsx      # NEW /view researcher inspector
    api/mock/
      sessions/route.ts                  # POST create session (goal) → {session_id, root_job_id}
      sessions/[sid]/full/route.ts       # snapshot replay (FullSession)
      sessions/[sid]/stream/route.ts     # SSE: the dummy streaming server (EventEnvelope)
      sessions/[sid]/messages/route.ts   # follow-up turns
      loop/route.ts                      # POST create autonomous loop
      loop/[sid]/stream/route.ts         # SSE: autonomous-loop events
      loop/[sid]/stop/route.ts           # user stop
  lib/
    sim/
      rng.ts          # seeded PRNG (mulberry32) + helpers (pick, jitter, noise, gauss)
      scenario.ts     # goal string → plausible research plan (strategies, subagents, baselines)
      narrative.ts    # templated prose for lead + sub-agent token streams
      timeline.ts     # plan → ordered EventEnvelope[] with pacing metadata
      artifacts.ts    # deterministic artifact specs (gridworld, plots, heatmaps)
      loop.ts         # multi-round autonomous-loop event generator
      store.ts        # in-memory session registry (sid → scenario+seed) for route handlers
    api.ts            # MOCK drop-in: streamSession/createSession/fetchFullSession → /api/mock
    types.ts  session-reducer.ts  session-stats.ts  status-colors.ts  utils.ts   # copied from web
    settings-store.ts                                                            # copied
    auth-fake.ts      # replaces Clerk: a no-op provider + fixed demo user
  components/
    # copied verbatim from web/components:
    chat-transcript  chat-composer  agent-graph  agent-tree  tree-panel  subagent-card
    metric-chart  session-header  context-bar  app-sidebar  app-shell  status-dot
    eyebrow  page-header  session-row  resize-handle  graph-node  graph-edge
    landing/*  ui/*
    # NEW:
    researcher-view/{work-log,tool-timeline,metric-grid,outputs-gallery,researcher-header}.tsx
    autonomous/{loop-composer,round-timeline,round-card,loop-metrics,stop-banner}.tsx
    sim/{gridworld-rollout,plot-thumbnail,heatmap}.tsx
  hooks/  # copied: use-session, use-sessions, use-chat-submit, use-resizable-pane,
          # use-reduced-motion, use-force-graph, use-pan-zoom  (+ NEW use-loop, use-researcher)
```

## 4. The simulation engine (`lib/sim/`)

The engine is pure, deterministic-given-seed, and framework-agnostic (testable in
isolation). It produces an ordered list of `(delayMs, EventEnvelope)` tuples that the
route handler replays with real sleeps.

### 4.1 `rng.ts`
- `mulberry32(seed)` → `() => number` in [0,1). **No `Math.random` in the codebase**
  (enforced by a lint/test guard).
- Helpers: `pick(rng, arr)`, `weightedPick`, `jitter(rng, base, spreadPct)`,
  `gaussian(rng, mean, sd)`, `seedFromString(s)`.

### 4.2 `scenario.ts`
- Input: a goal string (any text). Output: a `Scenario`:
  - extracts keywords / domain hints (env name, algorithm, metric);
  - selects 2–4 strategy directions from a library (Curiosity/ICM, reward shaping,
    GAE-λ + batch sweep, frame-stack+LSTM, SAC baseline, entropy schedule, …);
  - assigns sub-agents `A/B/C/D`, each with a `kind`, a baseline reward, a target
    reward, a learning-curve shape (logistic + noise), a training-loss decay shape,
    and a sample-efficiency profile;
  - picks which strategy "wins" and which plateaus/fails — for narrative tension.
- Fully a function of the seed → same goal+nonce reproduces the same scenario.

### 4.3 `narrative.ts`
- Templated, RNG-varied prose for: the lead agent's plan, per-round reasoning,
  per-sub-agent work-log lines and "thinking", tool-call descriptions, and summaries.
- Templates interpolate scenario fields (strategy names, metrics) so text reads fresh
  and goal-relevant without an LLM.

### 4.4 `timeline.ts`
- Composes a `Scenario` into the `EventEnvelope` sequence for a single research run:
  1. lead `status: running` + lead `token` deltas (the plan, typewriter);
  2. `spawn` per sub-agent (builds the tree/graph);
  3. interleaved per-sub-agent `token` (work log), `log`, `metric` (reward climbing
     incrementally with noise), occasional `artifact`;
  4. `summary` per sub-agent as it finishes; lead `summary` + `status: done`.
- **Pacing (slow & incremental):** token deltas every ~40–80 ms (jittered);
  `metric` ticks every ~1–2 s; sub-agents start staggered; a full short run resolves
  over ~60–120 s. Pacing lives here as `delayMs`, so the route handler is a dumb player.

### 4.5 `artifacts.ts`
- Deterministic, code-generated visuals — **no image files, no external fetches**:
  - **gridworld rollout** — agent path through a MiniGrid-style maze (key→door), as
    a seeded sequence of frames rendered on canvas;
  - **training-curve plot** — a "saved plot" thumbnail rendered from the metric series;
  - **exploration/attention heatmap** — a seeded grid of intensities.
- Each `artifact` event carries a `kind` + params; the renderer (`components/sim/*`)
  draws it. URLs are synthetic (`mock://artifact/<id>`); `artifactUrl()` in the copied
  api stays compatible.

### 4.6 `loop.ts`
- The autonomous multi-round generator, faithful to `meta-planning/docs/autonomous-loops.md`:
  - emits `status`/`summary` events with a `phase` payload: `round_started`,
    `round_synthesized` (carries the round's `best_metric`), `loop_stopped` (carries
    `reason`);
  - each round internally runs a compact fan-out (reuses `scenario`/`timeline`);
  - best-metric improves across rounds then plateaus; stop policy decides terminal
    state (`completed` via goal_metric / max_rounds / plateau, `stopped` via user,
    `budget_exhausted`). Mirrors `infra/loop_policy.py` semantics.

### 4.7 `store.ts`
- In-memory map `sid → { scenario, seed, createdAt, goal, mode }`, populated by the
  POST create routes and read by the stream routes. Survives within one server
  process (sufficient for a demo). Loop records `loop:{sid}` analog kept here too.

## 5. The dummy streaming server (Route Handlers)

- `POST /api/mock/sessions` `{ goal }` → builds a `Scenario` (seed = hash(goal)+nonce),
  stores it, returns `{ session_id, root_job_id }`.
- `GET /api/mock/sessions/[sid]/stream` → a `ReadableStream` that walks the timeline,
  `await sleep(delayMs)` between frames, and writes SSE frames:
  `id: <n>\n` + `data: <json EventEnvelope>\n\n`. Honors `Last-Event-ID` to resume
  mid-timeline (so the copied `streamSession` reconnect/backoff logic works unchanged).
- `GET /api/mock/sessions/[sid]/full` → a `FullSession` snapshot (for replay of a
  finished session without re-streaming).
- `POST /api/mock/sessions/[sid]/messages` `{ content }` → appends a follow-up turn:
  injects a new user message + a generated lead response into the live timeline.
- Loop routes mirror the above for `/api/mock/loop/*`.

The mock `lib/api.ts` simply points `API_BASE` at the app's own origin + `/api/mock`,
so all copied hooks (`use-session`, `use-sessions`, `use-chat-submit`) work untouched.

## 6. Surfaces

### 6.1 Landing + sign-in (full-site clone)
Copied `landing/*` (hero, nav, animated agent-tree field, live sim cards). The
sign-in page is a single "Enter demo" button that sets a fake session cookie/local
flag via `auth-fake.ts`; the shell reads a fixed demo user (no Clerk, no network).

### 6.2 Shell pages
Copied `overview`, `projects`, `settings`, `integrations`, `account`, driven by the
mock session list (`session-stats`). `overview` shows live stat cards + recent
sessions. Nav gains an **Autonomous** entry.

### 6.3 Research chat (free-interactive) — `/app`
Identical to the real `/app`: type any goal (or pick a preset chip) → POST creates a
session → live streamed transcript (typewriter), right-rail **tree** + **subagent
cards** (live reward sparklines) + **artifacts**, force-directed **graph** overlay.
**Plus in-chat long-term graphs:** an aggregate panel (reward / sample-efficiency /
training-loss) across the run — a multi-series extension of `metric-chart`.

### 6.4 `/view/[jobId]` — researcher inspector (NEW)
Drilling into a sub-agent (from tree / graph node / subagent card) opens the GUI for
*that* simulated researcher:
- **Researcher header** — name, kind, status, budget, elapsed.
- **Work-log** — its live token stream ("thinking" + actions), typewriter.
- **Tool-call timeline** — ordered tool invocations with args/results.
- **Metric grid** — three long-term charts: reward, training loss, sample-efficiency.
- **Outputs gallery** — mocked artifacts: gridworld rollout animation, eval frames,
  generated plot thumbnails, heatmaps.
Reachable while the run is live (streams that job's slice) or after (replay).

### 6.5 `/autonomous` — autonomous-loops section (NEW)
- **Loop composer** — goal + `max_rounds` + `goal_metric` (+ optional plateau_k).
- **Round timeline** — rounds tick by slowly; each round expands into its fan-out.
- **Loop metrics** — cross-round long-term graphs: best-metric per round, plateau
  band, sample-efficiency over rounds.
- **Stop policy / terminal state** — faithful to the real policy: the terminal
  *status* is `completed` (with a *reason* of goal-met / max-rounds / plateau),
  `stopped` (user), `budget_exhausted`, or `failed`. Shows status + reason, plus a
  user **Stop** button.

## 7. Long-term graphs (reward / efficiency / loss)

- Extend the `MetricPoint`/metric path so `metric` events can carry multiple series:
  `{ step, reward, loss?, efficiency? }`. The copied `RewardChart` stays as-is for
  reward; add a `MetricGrid` (small-multiples) and a `MultiSeriesChart` for the loss /
  efficiency overlays. Used in chat (§6.3), `/view` (§6.4), and `/autonomous` (§6.5).
- Curves are generated incrementally (one point per `metric` tick) so they **grow
  slowly on screen** rather than appearing complete.

## 8. Testing

- **Vitest** (copied config):
  - engine determinism: same seed → byte-identical timeline; different nonce → different;
  - `session-reducer` folds a generated stream into the expected `SessionState`;
  - `EventEnvelope` conformance: every emitted frame validates against the type;
  - no-`Math.random` guard (grep/lint test that fails if `Math.random` appears in `lib/`);
  - loop stop-policy parity: terminal states match `infra/loop_policy.py` semantics;
  - component smoke tests for the NEW surfaces (researcher-view, autonomous).
- **Manual run**: `pnpm dev`, walk the full flow, confirm slow incremental streaming.

## 9. Adversarial review (per CLAUDE.md)

After a working build, dispatch adversarial reviewers to attack fidelity:
1. **Protocol reviewer** — diff emitted events against `infra/schemas.py` + the real
   reducer's expectations; flag any field the real backend would send that we omit.
2. **Visual-parity reviewer** — compare demo screens against the real `web/` app;
   flag drift in spacing, color tokens, typography, component behavior.
3. **Realism reviewer** — does the pacing/curve-shape/narrative "feel real"? Flag
   tells that betray a mock (too-smooth curves, repeated prose, unrealistic metrics).
4. **UX-flow reviewer** — dead ends, missing empty/error/loading states, navigation
   gaps across the full-site clone.
Findings triaged and fixed before declaring done.

## 10. Assumptions & risks (challenge these)

- **In-memory store** loses sessions on server restart — acceptable for a demo; noted
  so no one expects persistence.
- **Copy-not-import** means the demo can drift from `web/` over time. Acceptable: the
  demo is a frozen showcase, not a shared library. A short README in `demo/` records
  the copy provenance + date.
- **Full-site clone is large.** The plan will phase it: (P1) scaffold + design system
  + mock api wiring; (P2) engine + dummy server + chat streaming; (P3) `/view`;
  (P4) `/autonomous`; (P5) landing/shell pages; (P6) artifacts/visuals polish;
  (P7) tests + adversarial review.
- **`metric` multi-series extension** must stay backward-compatible with the copied
  reducer (reward-only consumers must not break).
- **Determinism vs. "semi-stochastic"**: resolved as seed=hash(goal)+nonce — varied
  across sessions, replayable within one. If the user wants *identical* runs per goal,
  drop the nonce (one-line change).
```
