# Resizable sidebar + Obsidian-style agent graph overlay — design

**Date:** 2026-06-21
**Status:** approved (design); pending spec review
**Branch:** `feat/agent-graph-overlay`

## Problem

Two gaps in the live research UI ([`web/app/page.tsx`](../../../web/app/page.tsx)):

1. The left sidebar is a **fixed** `w-[264px]` (page.tsx) — users can't widen it to
   read long session goals or narrow it to reclaim space.
2. The agent tree ([`web/components/agent-tree.tsx`](../../../web/components/agent-tree.tsx))
   is a **static, non-interactive SVG** in a cramped right rail. The session already
   streams rich per-job telemetry (status, metrics, logs, token deltas) but the tree
   shows only a status dot per node. There is no way to explore the subagent graph,
   and the live SSE flow is invisible in the topology.

We want: (a) a **resizable** left sidebar, and (b) clicking the tree to open an
**immersive, full-screen, Obsidian-style force-directed graph** where every node
shows its **live SSE activity** with cool animations.

## Locked decisions (from brainstorming)

- **Graph feel:** *pure* force-directed physics (free, no hierarchy bias) — nodes
  float, repel, edges are springs, drag-to-jiggle, like Obsidian's graph view.
- **Placement:** **full-screen overlay** over the app; Esc / click-out closes. The
  existing compact tree in the right rail stays as the entry point.
- **Stack:** **d3-force engine + React/HTML nodes over an SVG edge layer** (Approach
  A). d3-force computes positions; nodes are React components (so live SSE content
  drops straight in); edges are SVG paths underneath; pan/zoom/drag is hand-rolled.
  Rejected: react-force-graph (canvas nodes can't host live React content) and React
  Flow (not physics-native; heavier).

## Key invariant that makes this safe

All graph data is **derived from the same `SessionState`** that already drives the
right rail, built by folding the event stream in
[`web/lib/session-reducer.ts`](../../../web/lib/session-reducer.ts). The overlay adds
**no new data source** — it is a second view of existing state. Consequences:

- The compact tree and the overlay can never diverge.
- Closing the overlay loses nothing; state lives in `useSession`.
- Live node add/remove (new subagent spawns) falls out of the reducer for free.

## Event routing — what each node can show

Every `EventEnvelope` carries a required `job_id`
([`infra/schemas.py`](../../../infra/schemas.py)); the runner relays each subagent's
events stamped with *its own* id ([`runner/internal_api.py`](../../../runner/internal_api.py)).
So per-node live content is feasible. Nuance to respect:

- **Token-level typewriter is root-only today.** `token` events carry
  `job_id = root, depth = 0` (per the token-streaming spec). So only the lead-agent
  node gets character-by-character streaming.
- **Subagent nodes** show their latest **job-scoped** activity: `log` content,
  `summary`, `status`, and `metric` (reward). This is the "SSE within the node" for
  subagents. If subagents later emit `token` events with their own id, nodes pick it
  up with no change (the reducer keys on `job_id`).

## Deliverable 1 — Resizable left sidebar

- **New** `web/hooks/use-resizable-pane.ts`: pointer-drag resize. Clamp **200–480px**
  (default **264**). **Persist to `localStorage`** under a stable key. Double-click
  the handle → reset to default. SSR-safe: initial render uses the default; the
  stored width is read in a `useEffect` after mount (no hydration mismatch).
  Returns `{ width, onHandlePointerDown, reset }`.
- **New** `web/components/resize-handle.tsx`: a 4px-wide hit area on the sidebar's
  right edge, `cursor: col-resize`, a hairline that brightens on hover/drag, ARIA
  `role="separator"` + keyboard arrows for a11y.
- **Edit** `web/app/page.tsx`: wrap the desktop sidebar container (currently
  `hidden w-[264px] shrink-0 md:flex`) with `style={{ width }}` and render the
  handle. The internal chat list already scrolls (`ScrollArea`). The mobile
  slide-over drawer is untouched.

## Deliverable 2 — Force-graph overlay

### Reducer / selectors (single source of truth)

- **Edit** `web/lib/types.ts`:
  - Extend `JobView` with `lastLine?: string` and `streaming?: boolean`.
  - Add `GraphNode { id, label, kind, status, depth, isRoot, reward?, rewards,
    lastLine?, streaming? }` and `GraphLink { source: string; target: string;
    active: boolean }` (active = child is running).
- **Edit** `web/lib/session-reducer.ts`:
  - In `applyEvent`, additively stamp the job's `lastLine`/`streaming` from
    job-scoped `log` (content), `token` (running delta + `streaming = !final`), and
    `summary` (`streaming = false`). Existing transcript behavior is unchanged.
  - Add selector `graphOf(state): { nodes: GraphNode[]; links: GraphLink[] }`,
    derived from `state.jobs` + `parentId`. Sibling labels reuse the existing
    `letter(i)` scheme; root label "Main agent".

### Hooks

- **New** `web/hooks/use-force-graph.ts`: wraps `d3-force` — `forceManyBody` (repel),
  `forceLink` (springs), `forceCollide` (no overlap), `forceCenter`. Inputs
  nodes/links keyed by id; **reconciles** on data change (preserves existing node
  positions, adds new nodes near their parent, removes gone nodes, reheats `alpha`).
  Exposes live positions via a **ref + rAF tick callback** (never `setState` per
  tick), plus `pin(id)`, `release(id)`, `reheat()`.
- **New** `web/hooks/use-pan-zoom.ts`: viewport transform `{ x, y, k }`. Drag
  background to pan; wheel to zoom (clamped, cursor-anchored); `fitToView(bounds)`
  on open; `reset()`.

### Components

- **New** `web/components/agent-graph.tsx`: full-screen `fixed` overlay — backdrop,
  header (session goal · node count · close button), legend, "reset view" control.
  Esc and click-out close. Composes the SVG edge layer + React node layer inside the
  pan/zoom viewport. Delegates physics + viewport to the hooks to stay well under the
  800-line limit (CLAUDE.md).
- **New** `web/components/graph-node.tsx`: the rich live node — status ring (color via
  the existing `STATUS_HEX`), label + kind, a live **streaming line** (`lastLine`
  with a typewriter caret while `streaming`), an inline **reward sparkline** (reuse
  `RewardChart` with `spark`), reward value. Drag-to-pin; hover/selected states;
  **scale-in** on mount.
- **New** `web/components/graph-edge.tsx`: parent→child SVG path; when `active`, an
  **animated flow** (traveling dash / particle) conveys live SSE moving down the
  tree; fades when the child finishes.
- **Edit** `web/components/tree-panel.tsx`: make the compact `AgentTree` a clickable
  button (with an explicit "expand" affordance + `aria-label`) that calls
  `onExpand`.
- **Edit** `web/app/page.tsx`: add `graphOpen` state; render `<AgentGraph>` when open;
  wire `TreePanel onExpand`.

## Deliverable 3 — "Make it look cool" (animation layer)

- **New-subagent enter:** node scale/fade-in; sim `reheat()` so the graph re-settles
  organically.
- **Running status:** pulsing sunset glow ring on the node (CSS keyframes).
- **Edge flow:** animated dash/particle parent→child while the child runs.
- **Streaming text:** node's current line updates live with a typewriter caret while
  `streaming`.
- **Live reward sparkline:** updates as `metric` events arrive.
- **Background:** faint radial vignette so the graph "floats" on the dark canvas.
- **Accessibility:** all continuous motion (pulse, flow, caret) is gated on
  `prefers-reduced-motion: no-preference`.

## Data flow

```
SSE → streamSession → applyEvent (now also stamps lastLine/streaming)
    → SessionState → graphOf(state) → { nodes, links }
    → use-force-graph (positions, rAF) + graph-node (live content)
```

The overlay and the right-rail tree read the identical state, so they stay in sync.

## Testing (vitest + testing-library, mirroring `web/**/__tests__`)

- `session-reducer.test.ts`: `graphOf` node/link shape; `lastLine`/`streaming`
  stamping from job-scoped `log`/`token`/`summary`; active-link = child running.
- `use-resizable-pane.test.ts`: clamp at min/max; persist + restore from localStorage;
  reset.
- `use-force-graph`: pure reconcile-by-id helper (add/remove/keep positions); mock rAF
  so no animation runs in jsdom.
- `agent-graph.test.tsx`: renders a node per job; Esc closes; clicking a node selects.
- `graph-node.test.tsx`: shows the typewriter caret only when `streaming`.

## Dependencies

- **Add:** `d3-force` + `@types/d3-force` (small, tree-shakeable). No three.js, no
  React Flow.

## Out of scope (YAGNI)

- Right-rail resize (only the *left* sidebar was requested).
- Persisting node positions across reloads.
- Minimap (graph is small — a lead agent + a handful of subagents).
- 3D / WebGL rendering.

## File / size budget (CLAUDE.md: < 800 lines, modular)

| File | New/Edit | Responsibility |
|------|----------|----------------|
| `hooks/use-resizable-pane.ts` | new | sidebar width state + persistence |
| `components/resize-handle.tsx` | new | drag handle UI |
| `lib/types.ts` | edit | `GraphNode`/`GraphLink`; `JobView` fields |
| `lib/session-reducer.ts` | edit | `graphOf` + `lastLine`/`streaming` stamping |
| `hooks/use-force-graph.ts` | new | d3-force sim + reconcile + rAF positions |
| `hooks/use-pan-zoom.ts` | new | viewport pan/zoom |
| `components/agent-graph.tsx` | new | overlay shell, composes layers |
| `components/graph-node.tsx` | new | live React node |
| `components/graph-edge.tsx` | new | animated SVG edge |
| `components/tree-panel.tsx` | edit | clickable tree → `onExpand` |
| `app/page.tsx` | edit | resizable wrapper + `graphOpen` overlay |
