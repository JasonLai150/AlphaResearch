# AlphaResearch — Interactive Demo

A high-fidelity, fully **mocked** version of the AlphaResearch console. It runs
with **no backend, no auth, and no API keys** — every stream, metric, and output
is generated locally by a seeded simulation engine.

```bash
cd demo
npm install
npm run dev      # http://localhost:3100
```

## What to try

- **Landing → "Enter demo"** (`/` → `/sign-in` → `/app`): no account needed.
- **Research chat** (`/app`): type any RL research goal (or pick a preset). The
  lead agent streams a plan, fans out sub-agents, and reports rewards back — live,
  slowly, token by token. Multi-turn: reply mid-run and the lead answers.
- **Right rail**: agent tree, sub-agent cards (live reward sparklines), artifacts,
  the force-graph overlay, and a **Metrics** overlay (long-term reward / loss /
  efficiency across all researchers).
- **`/view/{sid}/{jobId}`**: click a sub-agent to open its inspector — live work
  log, tool-call timeline, three long-term training curves, and mocked outputs
  (reward plot + gridworld rollout for MiniGrid envs).
- **Autonomous loops** (`/autonomous`): set a goal + round budget + target metric;
  watch rounds tick by, with cross-round long-term graphs, a stop policy
  (goal / plateau / budget), and a user **Stop** button.

## How the mock works

The fidelity principle is **swap the event source, not the renderer**. The real
SSE client (`lib/api.ts`), event reducer (`lib/session-reducer.ts`), types, and
components are copied verbatim from the production app. The only thing replaced is
where events come from: in-app Next.js route handlers under `app/api/mock/` emit
the exact same `EventEnvelope` SSE protocol, paced on a wall-clock so runs unfold
slowly and incrementally.

- `lib/sim/rng.ts` — seeded PRNG (no `Math.random`; a test guards this).
- `lib/sim/scenario.ts` — turns any goal into a plausible plan + training curves.
- `lib/sim/narrative.ts` — templated lead / researcher prose.
- `lib/sim/timeline.ts` — composes the timed `EventEnvelope` sequence.
- `lib/sim/loop.ts` / `loop-store.ts` — the autonomous multi-round model + stop policy.
- `lib/sim/store.ts` — in-memory session registry (resets on server restart).
- `lib/sim/artifacts.ts` — deterministic SVG plots / gridworld rollouts.

Everything is deterministic given a seed (seed = hash(goal) + a per-session nonce),
so a session is internally consistent and replayable, while different sessions vary.

## Tests

```bash
npm test        # 112 tests: engine determinism, reducer fold, SSE conformance, components
```

## Provenance

Copied from `web/` on 2026-06-21 and rewired for a standalone mock (Clerk removed,
data layer pointed at `/api/mock`). It's a frozen showcase, not a shared library —
it will drift from `web/` over time. Design spec:
`docs/superpowers/specs/2026-06-21-demo-high-fidelity-mock-design.md`.

### Known mock limitations (intentional, low-impact)

- The in-memory store resets on dev recompile / server restart (no persistence).
- Strategy blurbs are gridworld-flavored; for non-MiniGrid envs the prose is
  generic-ish (the env-specific gridworld *rollout* is correctly suppressed).
