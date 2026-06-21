# Resizable Sidebar + Obsidian-Style Agent Graph Overlay — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a drag-resizable left sidebar and a full-screen, pure force-directed agent graph whose nodes stream their live SSE activity with animations.

**Architecture:** All graph data is derived from the existing `SessionState` (built by `applyEvent` folding the SSE stream) — no new data source. d3-force computes node positions; nodes are React components (so live content drops in); edges are SVG paths underneath; pan/zoom/drag is hand-rolled. The overlay is a second view of the same state that drives the right rail, so they can never diverge.

**Tech Stack:** Next.js 15 · React 19 · Tailwind v4 · TypeScript · d3-force v3 (new) · Recharts (existing, sparkline) · vitest + @testing-library/react.

## Global Constraints

- Every file stays **< 800 lines**, one clear responsibility, single source of truth (CLAUDE.md).
- **Branch:** `feat/agent-graph-overlay`. Never commit to / push `main`. Commit after each task.
- **Only new dependency:** `d3-force` + `@types/d3-force`. No three.js, no React Flow.
- **Dark-only** design: use existing brand tokens (`canvas`, `canvas-card`, `hairline`, `ink`, `body`, `mute`, `sunset`, `destructive`). SVG needs hex literals (Tailwind classes don't apply) — reuse the shared `STATUS_HEX`.
- All continuous motion (pulse, edge flow, caret) gated on `prefers-reduced-motion: no-preference`.
- Reducer stays **deterministic & idempotent under replay**; **`token`/`log` events never create a job** (existing invariant — `session-reducer.test.ts` asserts `state.order === []` for a token-only stream).
- Tests run with **`globals: false`** → import `{ describe, it, expect, vi }` from `"vitest"` explicitly.
- **All `npx`/`npm`/`vitest` commands run from the `web/` directory.**

---

### Task 1: Resizable left sidebar

**Files:**
- Create: `web/hooks/use-resizable-pane.ts`
- Create: `web/hooks/__tests__/use-resizable-pane.test.ts`
- Create: `web/components/resize-handle.tsx`
- Modify: `web/app/page.tsx` (desktop sidebar wrapper, ~line 131)

**Interfaces:**
- Produces: `useResizablePane(opts: { key: string; min: number; max: number; initial: number }): { width: number; setWidth: (n: number) => void; reset: () => void }`
- Produces: `clampWidth(n: number, min: number, max: number): number` (pure, exported for test)
- Produces: `<ResizeHandle onResize={(deltaX: number) => void} onReset={() => void} />`

- [ ] **Step 1: Write the failing test**

`web/hooks/__tests__/use-resizable-pane.test.ts`:
```ts
import { describe, it, expect, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { clampWidth, useResizablePane } from "@/hooks/use-resizable-pane";

describe("clampWidth", () => {
  it("clamps below min and above max, passes through in range", () => {
    expect(clampWidth(120, 200, 480)).toBe(200);
    expect(clampWidth(900, 200, 480)).toBe(480);
    expect(clampWidth(300, 200, 480)).toBe(300);
  });
});

describe("useResizablePane", () => {
  beforeEach(() => localStorage.clear());

  it("starts at initial when no stored value", () => {
    const { result } = renderHook(() =>
      useResizablePane({ key: "k", min: 200, max: 480, initial: 264 })
    );
    expect(result.current.width).toBe(264);
  });

  it("clamps + persists on setWidth, and reset returns to initial", () => {
    const { result } = renderHook(() =>
      useResizablePane({ key: "sb", min: 200, max: 480, initial: 264 })
    );
    act(() => result.current.setWidth(9999));
    expect(result.current.width).toBe(480);
    expect(localStorage.getItem("sb")).toBe("480");
    act(() => result.current.reset());
    expect(result.current.width).toBe(264);
  });

  it("restores a previously stored width on mount", () => {
    localStorage.setItem("sb", "330");
    const { result } = renderHook(() =>
      useResizablePane({ key: "sb", min: 200, max: 480, initial: 264 })
    );
    expect(result.current.width).toBe(330);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run hooks/__tests__/use-resizable-pane.test.ts`
Expected: FAIL — `Cannot find module '@/hooks/use-resizable-pane'`.

- [ ] **Step 3: Write minimal implementation**

`web/hooks/use-resizable-pane.ts`:
```ts
"use client";

import { useCallback, useEffect, useState } from "react";

export function clampWidth(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}

/**
 * Persisted, clamped width for a draggable pane. SSR-safe: the first render
 * uses `initial` (so server and client markup match); any stored width is read
 * from localStorage in an effect after mount.
 */
export function useResizablePane(opts: {
  key: string;
  min: number;
  max: number;
  initial: number;
}) {
  const { key, min, max, initial } = opts;
  const [width, setWidthState] = useState(initial);

  useEffect(() => {
    const stored = localStorage.getItem(key);
    if (stored != null) {
      const n = Number(stored);
      if (!Number.isNaN(n)) setWidthState(clampWidth(n, min, max));
    }
  }, [key, min, max]);

  const setWidth = useCallback(
    (n: number) => {
      const w = clampWidth(n, min, max);
      setWidthState(w);
      localStorage.setItem(key, String(w));
    },
    [key, min, max]
  );

  const reset = useCallback(() => {
    setWidthState(initial);
    localStorage.removeItem(key);
  }, [key, initial]);

  return { width, setWidth, reset };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run hooks/__tests__/use-resizable-pane.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Write the ResizeHandle component**

`web/components/resize-handle.tsx`:
```tsx
"use client";

import { useCallback, useRef } from "react";

import { cn } from "@/lib/utils";

/**
 * A thin vertical drag handle for resizing the pane to its left. Reports the
 * horizontal pointer delta per move; double-click resets. Keyboard: Left/Right
 * arrows nudge by 16px via the same onResize channel.
 */
export function ResizeHandle({
  onResize,
  onReset,
  className,
}: {
  onResize: (deltaX: number) => void;
  onReset: () => void;
  className?: string;
}) {
  const last = useRef<number | null>(null);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      (e.target as Element).setPointerCapture(e.pointerId);
      last.current = e.clientX;
    },
    []
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (last.current == null) return;
      const dx = e.clientX - last.current;
      last.current = e.clientX;
      if (dx !== 0) onResize(dx);
    },
    [onResize]
  );

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    last.current = null;
    (e.target as Element).releasePointerCapture(e.pointerId);
  }, []);

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize sidebar"
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onDoubleClick={onReset}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") onResize(-16);
        else if (e.key === "ArrowRight") onResize(16);
      }}
      className={cn(
        "group relative w-1.5 shrink-0 cursor-col-resize touch-none select-none",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className
      )}
    >
      <span
        aria-hidden
        className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-hairline transition-colors group-hover:bg-canvas-mid group-focus-visible:bg-sunset"
      />
    </div>
  );
}
```

- [ ] **Step 6: Wire the resizable sidebar into the page**

In `web/app/page.tsx`:
1. Add imports near the other hook/component imports:
```tsx
import { ResizeHandle } from "@/components/resize-handle";
import { useResizablePane } from "@/hooks/use-resizable-pane";
```
2. Inside `Page()`, after the existing `useState` calls:
```tsx
const {
  width: sidebarWidth,
  setWidth: setSidebarWidth,
  reset: resetSidebar,
} = useResizablePane({ key: "ar.sidebarWidth", min: 200, max: 480, initial: 264 });
```
3. Replace the desktop sidebar block (currently `<div className="hidden w-[264px] shrink-0 md:flex">{sidebar}</div>`) with:
```tsx
<div
  className="hidden shrink-0 md:flex"
  style={{ width: sidebarWidth }}
>
  {sidebar}
</div>
<ResizeHandle
  className="hidden md:block"
  onResize={(dx) => setSidebarWidth(sidebarWidth + dx)}
  onReset={resetSidebar}
/>
```

- [ ] **Step 7: Verify wiring (typecheck) and run the suite**

Run: `npx tsc --noEmit`
Expected: no errors.
Run: `npx vitest run`
Expected: all tests pass (existing + the 4 new).

- [ ] **Step 8: Commit**

```bash
git add web/hooks/use-resizable-pane.ts web/hooks/__tests__/use-resizable-pane.test.ts web/components/resize-handle.tsx web/app/page.tsx
git commit -m "feat(web): drag-resizable, persisted left sidebar"
```

---

### Task 2: Graph data model — types + reducer (`lastLine`/`streaming` + `graphOf`)

**Files:**
- Modify: `web/lib/types.ts` (add `GraphNode`, `GraphLink`; extend `JobView`)
- Modify: `web/lib/session-reducer.ts` (stamp live line; add `graphOf`)
- Modify: `web/lib/__tests__/session-reducer.test.ts` (append new describe block + import `graphOf`)

**Interfaces:**
- Consumes: existing `SessionState`, `JobView`, `AgentStatus`, `MetricPoint`, `letter()` (module-private in `session-reducer.ts`).
- Produces: `GraphNode`, `GraphLink` types; `graphOf(state: SessionState): { nodes: GraphNode[]; links: GraphLink[] }`.

- [ ] **Step 1: Add the types**

In `web/lib/types.ts`, extend `JobView` (add two optional fields) — insert after `rewards: MetricPoint[];`:
```ts
  /** Latest job-scoped activity line (from log/token/summary), for the graph node. */
  lastLine?: string;
  /** True while token deltas for this job are mid-flight (drives the node caret). */
  streaming?: boolean;
```
And add, after the `Subagent` interface:
```ts
/** A node in the force-directed agent graph (derived from SessionState). */
export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  status: AgentStatus;
  depth: number;
  isRoot: boolean;
  reward?: number;
  rewards: MetricPoint[];
  lastLine?: string;
  streaming?: boolean;
}

/** A parent→child edge; `active` is true while the child job is running. */
export interface GraphLink {
  source: string;
  target: string;
  active: boolean;
}
```

- [ ] **Step 2: Write the failing tests**

In `web/lib/__tests__/session-reducer.test.ts`, add `graphOf` to the import from `@/lib/session-reducer`, then append:
```ts
// ─── (i) graphOf builds nodes + links from the job graph ─────────────────────

describe("graphOf nodes and links", () => {
  it("maps jobs to nodes, root labeled 'Main agent', children A/B, links active when running", () => {
    const state = reduce([
      env({ type: "spawn", job_id: "root", parent_job_id: null, depth: 0, payload: { kind: "agent" } }),
      env({ type: "spawn", job_id: "c1", parent_job_id: "root", depth: 1, payload: { kind: "experiment", goal: "tune lr" } }),
      env({ type: "status", job_id: "c1", payload: { status: "running" } }),
      env({ type: "spawn", job_id: "c2", parent_job_id: "root", depth: 1, payload: { kind: "experiment" } }),
    ]);
    const { nodes, links } = graphOf(state);

    expect(nodes.map((n) => n.id)).toEqual(["root", "c1", "c2"]);
    expect(nodes[0]).toMatchObject({ isRoot: true, label: "Main agent", depth: 0 });
    expect(nodes[1]).toMatchObject({ isRoot: false, label: "A", kind: "tune lr" });
    expect(nodes[2].label).toBe("B");

    // One link per child; active iff the child is running.
    expect(links).toEqual([
      { source: "root", target: "c1", active: true },
      { source: "root", target: "c2", active: false },
    ]);
  });

  it("returns empty graph when there is no root", () => {
    expect(graphOf(emptyState(SESSION))).toEqual({ nodes: [], links: [] });
  });
});

// ─── (j) lastLine / streaming stamping ───────────────────────────────────────

describe("graph node live line stamping", () => {
  it("stamps a job's lastLine from a job-scoped log without creating a job from a token", () => {
    const state = reduce([
      env({ type: "spawn", job_id: "root", depth: 0, payload: {} }),
      env({ type: "log", job_id: "root", payload: { role: "assistant", content: "scoping the task" } }),
    ]);
    expect(state.jobs["root"].lastLine).toBe("scoping the task");
    expect(state.jobs["root"].streaming).toBe(false);
  });

  it("token deltas set streaming + grow the line on an existing job, never create one", () => {
    const state = reduce([
      env({ type: "spawn", job_id: "root", depth: 0, payload: {} }),
      env({ type: "token", job_id: "root", payload: { msg_id: "m#0", delta: "Hel", final: false } }),
      env({ type: "token", job_id: "root", payload: { msg_id: "m#0", delta: "lo", final: true } }),
    ]);
    expect(state.jobs["root"].lastLine).toBe("Hello");
    expect(state.jobs["root"].streaming).toBe(false);

    // Token for an unknown job must NOT create a job (preserves the invariant).
    const orphan = reduce([
      env({ type: "token", job_id: "ghost", payload: { msg_id: "x#0", delta: "hi", final: true } }),
    ]);
    expect(orphan.order).toEqual([]);
  });

  it("summary sets lastLine to the summary text", () => {
    const state = reduce([
      env({ type: "spawn", job_id: "j1", payload: {} }),
      env({ type: "summary", job_id: "j1", payload: { summary: "converged at 0.91" } }),
    ]);
    expect(state.jobs["j1"].lastLine).toBe("converged at 0.91");
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `npx vitest run lib/__tests__/session-reducer.test.ts -t "graphOf"`
Expected: FAIL — `graphOf is not a function` (and the live-line tests fail).

- [ ] **Step 4: Implement the reducer changes**

In `web/lib/session-reducer.ts`:

(a) Add a pure stamping helper after `appendTranscript`:
```ts
/*
  Stamp a job's live "current line" (for the graph node). Updates ONLY an
  existing job — never creates one — so the invariant "token/log events never
  create jobs" holds. Deterministic under replay (value = latest content). The
  line is tail-trimmed so a long stream can't bloat state.
*/
function stampJobLine(
  state: SessionState,
  id: string,
  line: string,
  streaming: boolean
): SessionState {
  if (!id || !line.trim()) return state;
  const job = state.jobs[id];
  if (!job) return state;
  const trimmed = line.length > 160 ? line.slice(line.length - 160) : line;
  return {
    ...state,
    jobs: { ...state.jobs, [id]: { ...job, lastLine: trimmed, streaming } },
  };
}
```

(b) In the `log` branch, replace the final `return appendTranscript(...)` with:
```ts
    const appended = appendTranscript(prev, {
      role: mapped,
      text: String(p.content ?? ""),
      toolName: (p.tool_name as string) ?? undefined,
    });
    return stampJobLine(appended, env.job_id, String(p.content ?? ""), false);
```

(c) In the `token` branch, replace its body with one that also stamps the job:
```ts
  if (env.type === "token") {
    const msgId = String(p.msg_id ?? "");
    const delta = String(p.delta ?? "");
    const final = Boolean(p.final);
    const i = prev.transcript.findIndex((t) => t.msgId === msgId);
    let next: SessionState;
    let line: string;
    if (i >= 0) {
      const transcript = prev.transcript.slice();
      line = transcript[i].text + delta;
      transcript[i] = { ...transcript[i], text: line, streaming: !final };
      next = { ...prev, transcript };
    } else {
      line = delta;
      next = appendTranscript(prev, {
        role: "assistant",
        text: delta,
        msgId,
        streaming: !final,
      });
    }
    return stampJobLine(next, env.job_id, line, !final);
  }
```

(d) In the `summary` case of the switch, after `if (p.summary != null) job.summary = String(p.summary);` add:
```ts
      if (p.summary != null) job.lastLine = String(p.summary);
      job.streaming = false;
```

(e) Append the `graphOf` selector at the end of the selectors section:
```ts
export function graphOf(state: SessionState): {
  nodes: GraphNode[];
  links: GraphLink[];
} {
  if (!state.rootId) return { nodes: [], links: [] };
  let childN = 0;
  const nodes: GraphNode[] = state.order.map((id) => {
    const j = state.jobs[id];
    const isRoot = id === state.rootId;
    let label: string;
    if (isRoot) label = "Main agent";
    else if (j.parentId === state.rootId) label = letter(childN++);
    else label = (j.goal || j.kind).slice(0, 16);
    return {
      id,
      label,
      kind: j.goal || (j.kind === "experiment" ? "Experiment" : "Research"),
      status: j.status,
      depth: j.depth,
      isRoot,
      reward: j.lastReward,
      rewards: j.rewards,
      lastLine: j.lastLine,
      streaming: j.streaming,
    };
  });
  const links: GraphLink[] = state.order
    .map((id) => state.jobs[id])
    .filter((j) => j.parentId != null && state.jobs[j.parentId])
    .map((j) => ({
      source: j.parentId as string,
      target: j.id,
      active: j.status === "running",
    }));
  return { nodes, links };
}
```
Add `GraphLink, GraphNode` to the type import at the top of the file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `npx vitest run lib/__tests__/session-reducer.test.ts`
Expected: PASS — the new `graphOf` + live-line tests AND all pre-existing reducer tests (determinism/idempotency unaffected).

- [ ] **Step 6: Commit**

```bash
git add web/lib/types.ts web/lib/session-reducer.ts web/lib/__tests__/session-reducer.test.ts
git commit -m "feat(web): graphOf selector + per-node live line in reducer"
```

---

### Task 3: Force-graph hook (`reconcileNodes` + `useForceGraph`)

**Files:**
- Modify: `web/package.json` (add `d3-force`, `@types/d3-force`)
- Create: `web/hooks/use-force-graph.ts`
- Create: `web/hooks/__tests__/force-graph.test.ts`

**Interfaces:**
- Consumes: `GraphNode`, `GraphLink` (Task 2).
- Produces: `SimNode` (= `GraphNode & { x: number; y: number; fx?: number | null; fy?: number | null }`).
- Produces: `reconcileNodes(prev: SimNode[], next: GraphNode[], center: { x: number; y: number }): SimNode[]` (pure).
- Produces: `useForceGraph(graph, { width, height }): { nodes: SimNode[]; links: GraphLink[]; pin(id,x,y): void; release(id): void; reheat(): void }`.

- [ ] **Step 1: Add the dependency**

Run: `npm install d3-force@^3 && npm install -D @types/d3-force@^3`
Expected: `package.json` gains both entries; lockfile updates.

- [ ] **Step 2: Write the failing test (pure reconcile)**

`web/hooks/__tests__/force-graph.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { reconcileNodes, type SimNode } from "@/hooks/use-force-graph";
import type { GraphNode } from "@/lib/types";

function gn(id: string, over: Partial<GraphNode> = {}): GraphNode {
  return { id, label: id, kind: "Research", status: "running", depth: 1, isRoot: false, rewards: [], ...over };
}

describe("reconcileNodes", () => {
  it("preserves positions of existing nodes and refreshes their data", () => {
    const prev: SimNode[] = [{ ...gn("root"), x: 12, y: 34 }];
    const out = reconcileNodes(prev, [gn("root", { status: "done" })], { x: 50, y: 50 });
    expect(out[0].x).toBe(12);
    expect(out[0].y).toBe(34);
    expect(out[0].status).toBe("done");
  });

  it("seeds brand-new nodes at the center", () => {
    const out = reconcileNodes([], [gn("c1")], { x: 50, y: 60 });
    expect(out[0].x).toBe(50);
    expect(out[0].y).toBe(60);
  });

  it("drops nodes no longer present", () => {
    const prev: SimNode[] = [{ ...gn("a"), x: 1, y: 1 }, { ...gn("b"), x: 2, y: 2 }];
    const out = reconcileNodes(prev, [gn("a")], { x: 0, y: 0 });
    expect(out.map((n) => n.id)).toEqual(["a"]);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npx vitest run hooks/__tests__/force-graph.test.ts`
Expected: FAIL — `Cannot find module '@/hooks/use-force-graph'`.

- [ ] **Step 4: Implement the hook**

`web/hooks/use-force-graph.ts`:
```ts
"use client";

import { useEffect, useRef, useState } from "react";
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
} from "d3-force";

import type { GraphLink, GraphNode } from "@/lib/types";

export type SimNode = GraphNode & {
  x: number;
  y: number;
  fx?: number | null;
  fy?: number | null;
};

/**
 * Merge fresh graph data into the running simulation's nodes: keep the live
 * x/y (and any pin fx/fy) of nodes that still exist, refresh their data,
 * seed brand-new nodes at the center so they animate outward, and drop nodes
 * that disappeared. Pure — the sim wiring lives in useForceGraph.
 */
export function reconcileNodes(
  prev: SimNode[],
  next: GraphNode[],
  center: { x: number; y: number }
): SimNode[] {
  const byId = new Map(prev.map((n) => [n.id, n]));
  return next.map((n) => {
    const existing = byId.get(n.id);
    if (existing) return { ...existing, ...n };
    return { ...n, x: center.x, y: center.y };
  });
}

export function useForceGraph(
  graph: { nodes: GraphNode[]; links: GraphLink[] },
  size: { width: number; height: number }
) {
  const simRef = useRef<Simulation<SimNode, undefined> | null>(null);
  const nodesRef = useRef<SimNode[]>([]);
  const [nodes, setNodes] = useState<SimNode[]>([]);

  // Create the simulation once.
  useEffect(() => {
    const sim = forceSimulation<SimNode>([])
      .force("charge", forceManyBody().strength(-340))
      .force("collide", forceCollide(58))
      .force("center", forceCenter(size.width / 2, size.height / 2))
      .on("tick", () => setNodes([...nodesRef.current]));
    sim.force(
      "link",
      forceLink<SimNode, GraphLink>([])
        .id((d) => d.id)
        .distance(120)
        .strength(0.4)
    );
    simRef.current = sim;
    return () => {
      sim.stop();
      simRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the center force in sync with the viewport size.
  useEffect(() => {
    const sim = simRef.current;
    if (!sim) return;
    sim.force("center", forceCenter(size.width / 2, size.height / 2));
  }, [size.width, size.height]);

  // Reconcile on data change and reheat so the layout re-settles.
  useEffect(() => {
    const sim = simRef.current;
    if (!sim) return;
    const merged = reconcileNodes(nodesRef.current, graph.nodes, {
      x: size.width / 2,
      y: size.height / 2,
    });
    nodesRef.current = merged;
    sim.nodes(merged);
    // forceLink mutates link source/target into node refs; pass fresh copies.
    sim.force(
      "link",
      forceLink<SimNode, GraphLink>(graph.links.map((l) => ({ ...l })))
        .id((d) => d.id)
        .distance(120)
        .strength(0.4)
    );
    sim.alpha(0.9).restart();
    setNodes([...merged]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph.nodes, graph.links]);

  const pin = (id: string, x: number, y: number) => {
    const n = nodesRef.current.find((m) => m.id === id);
    if (!n) return;
    n.fx = x;
    n.fy = y;
    simRef.current?.alphaTarget(0.3).restart();
  };
  const release = (id: string) => {
    const n = nodesRef.current.find((m) => m.id === id);
    if (n) {
      n.fx = null;
      n.fy = null;
    }
    simRef.current?.alphaTarget(0);
  };
  const reheat = () => simRef.current?.alpha(0.9).restart();

  return { nodes, links: graph.links, pin, release, reheat };
}
```

- [ ] **Step 5: Run test + typecheck**

Run: `npx vitest run hooks/__tests__/force-graph.test.ts`
Expected: PASS (3 tests).
Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add web/package.json web/package-lock.json web/hooks/use-force-graph.ts web/hooks/__tests__/force-graph.test.ts
git commit -m "feat(web): d3-force graph hook with position reconcile"
```

---

### Task 4: Pan/zoom hook (`zoomAt` + `fitView` + `usePanZoom`)

**Files:**
- Create: `web/hooks/use-pan-zoom.ts`
- Create: `web/hooks/__tests__/pan-zoom.test.ts`

**Interfaces:**
- Produces: `Transform = { x: number; y: number; k: number }`.
- Produces: `zoomAt(t, cursor, factor, bounds?): Transform` (pure).
- Produces: `fitView(content, viewport, padding?): Transform` (pure).
- Produces: `usePanZoom(): { transform; onWheel; onPointerDown; onPointerMove; onPointerUp; setTransform; reset }`.

- [ ] **Step 1: Write the failing test**

`web/hooks/__tests__/pan-zoom.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { zoomAt, fitView } from "@/hooks/use-pan-zoom";

describe("zoomAt", () => {
  it("keeps the cursor point fixed while scaling", () => {
    const t = { x: 0, y: 0, k: 1 };
    const next = zoomAt(t, { x: 100, y: 100 }, 2);
    expect(next.k).toBe(2);
    // world point under the cursor is unchanged: (cursor - x) / k constant
    expect((100 - t.x) / t.k).toBeCloseTo((100 - next.x) / next.k, 6);
  });

  it("clamps scale to bounds", () => {
    expect(zoomAt({ x: 0, y: 0, k: 1 }, { x: 0, y: 0 }, 100, [0.2, 4]).k).toBe(4);
    expect(zoomAt({ x: 0, y: 0, k: 1 }, { x: 0, y: 0 }, 0.0001, [0.2, 4]).k).toBe(0.2);
  });
});

describe("fitView", () => {
  it("centers content within the viewport", () => {
    const t = fitView(
      { minX: 0, minY: 0, maxX: 100, maxY: 100 },
      { width: 300, height: 300 },
      0
    );
    expect(t.k).toBeCloseTo(3, 6);
    // content center (50,50) maps to viewport center (150,150)
    expect(t.x + 50 * t.k).toBeCloseTo(150, 6);
    expect(t.y + 50 * t.k).toBeCloseTo(150, 6);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run hooks/__tests__/pan-zoom.test.ts`
Expected: FAIL — `Cannot find module '@/hooks/use-pan-zoom'`.

- [ ] **Step 3: Implement the hook**

`web/hooks/use-pan-zoom.ts`:
```ts
"use client";

import { useCallback, useRef, useState } from "react";

export interface Transform {
  x: number;
  y: number;
  k: number;
}

const DEFAULT_BOUNDS: [number, number] = [0.25, 3];

/** Zoom by `factor` while keeping the world point under `cursor` fixed. */
export function zoomAt(
  t: Transform,
  cursor: { x: number; y: number },
  factor: number,
  bounds: [number, number] = DEFAULT_BOUNDS
): Transform {
  const k = Math.min(bounds[1], Math.max(bounds[0], t.k * factor));
  const scale = k / t.k;
  return {
    k,
    x: cursor.x - (cursor.x - t.x) * scale,
    y: cursor.y - (cursor.y - t.y) * scale,
  };
}

/** Compute a transform that fits `content` bounds inside `viewport`. */
export function fitView(
  content: { minX: number; minY: number; maxX: number; maxY: number },
  viewport: { width: number; height: number },
  padding = 80,
  bounds: [number, number] = DEFAULT_BOUNDS
): Transform {
  const cw = Math.max(content.maxX - content.minX, 1);
  const ch = Math.max(content.maxY - content.minY, 1);
  const k = Math.min(
    bounds[1],
    Math.max(
      bounds[0],
      Math.min(
        (viewport.width - padding * 2) / cw,
        (viewport.height - padding * 2) / ch
      )
    )
  );
  const cx = (content.minX + content.maxX) / 2;
  const cy = (content.minY + content.maxY) / 2;
  return { k, x: viewport.width / 2 - cx * k, y: viewport.height / 2 - cy * k };
}

export function usePanZoom(initial: Transform = { x: 0, y: 0, k: 1 }) {
  const [transform, setTransform] = useState<Transform>(initial);
  const panning = useRef<{ x: number; y: number } | null>(null);

  const onWheel = useCallback((e: React.WheelEvent) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const cursor = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    setTransform((t) => zoomAt(t, cursor, factor));
  }, []);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    // Only pan when the background itself is grabbed (nodes stop propagation).
    if (e.target !== e.currentTarget) return;
    panning.current = { x: e.clientX, y: e.clientY };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const p = panning.current;
    if (!p) return;
    const dx = e.clientX - p.x;
    const dy = e.clientY - p.y;
    panning.current = { x: e.clientX, y: e.clientY };
    setTransform((t) => ({ ...t, x: t.x + dx, y: t.y + dy }));
  }, []);

  const onPointerUp = useCallback(() => {
    panning.current = null;
  }, []);

  const reset = useCallback(() => setTransform(initial), [initial]);

  return { transform, setTransform, onWheel, onPointerDown, onPointerMove, onPointerUp, reset };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run hooks/__tests__/pan-zoom.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add web/hooks/use-pan-zoom.ts web/hooks/__tests__/pan-zoom.test.ts
git commit -m "feat(web): pan/zoom viewport hook"
```

---

### Task 5: Shared status colors + live graph node

**Files:**
- Create: `web/lib/status-colors.ts`
- Modify: `web/components/agent-tree.tsx` (import shared `STATUS_HEX`, drop the local copy)
- Create: `web/components/graph-node.tsx`
- Create: `web/components/__tests__/graph-node.test.tsx`
- Modify: `web/app/globals.css` (graph keyframes, reduced-motion-gated)

**Interfaces:**
- Consumes: `SimNode` (Task 3), `RewardChart` (`@/components/metric-chart`).
- Produces: `STATUS_HEX: Record<AgentStatus, string>`.
- Produces: `<GraphNode node={SimNode} selected={boolean} onPointerDown={(e) => void} onSelect={() => void} />`.

- [ ] **Step 1: Extract the shared status palette**

`web/lib/status-colors.ts`:
```ts
import type { AgentStatus } from "@/lib/types";

/** Brand hexes for SVG/graph use (Tailwind classes don't apply to SVG fills). */
export const STATUS_HEX: Record<AgentStatus, string> = {
  running: "#ff7a17",
  done: "#ffffff",
  queued: "#7d8187",
  pending: "#7d8187",
  failed: "#ff7b72",
  cancelled: "#7d8187",
};
```
In `web/components/agent-tree.tsx`: delete the local `const STATUS_HEX: Record<AgentStatus, string> = {…};` block and add `import { STATUS_HEX } from "@/lib/status-colors";`.

- [ ] **Step 2: Add graph keyframes to globals.css**

Append to `web/app/globals.css`:
```css
@layer utilities {
  @keyframes ar-pulse-ring {
    0%, 100% { opacity: 0.55; transform: scale(1); }
    50% { opacity: 0.15; transform: scale(1.35); }
  }
  @keyframes ar-caret {
    0%, 100% { opacity: 1; }
    50% { opacity: 0; }
  }
  @keyframes ar-edge-flow {
    to { stroke-dashoffset: -24; }
  }
  .ar-node-pulse { animation: ar-pulse-ring 1.8s ease-in-out infinite; }
  .ar-caret { animation: ar-caret 1s step-end infinite; }
  .ar-edge-flow { stroke-dasharray: 4 8; animation: ar-edge-flow 0.7s linear infinite; }
  @media (prefers-reduced-motion: reduce) {
    .ar-node-pulse, .ar-caret, .ar-edge-flow { animation: none; }
  }
}
```

- [ ] **Step 3: Write the failing test**

`web/components/__tests__/graph-node.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeAll, afterEach } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

beforeAll(() => {
  if (!("ResizeObserver" in globalThis)) {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  }
});
afterEach(() => cleanup());

import { GraphNode } from "@/components/graph-node";
import type { SimNode } from "@/hooks/use-force-graph";

function node(over: Partial<SimNode> = {}): SimNode {
  return {
    id: "c1", label: "A", kind: "tune lr", status: "running", depth: 1,
    isRoot: false, rewards: [], x: 0, y: 0, ...over,
  };
}

describe("GraphNode", () => {
  it("renders label and kind", () => {
    render(<GraphNode node={node()} selected={false} onPointerDown={vi.fn()} onSelect={vi.fn()} />);
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText(/tune lr/)).toBeInTheDocument();
  });

  it("shows the typewriter caret only while streaming", () => {
    const { rerender, container } = render(
      <GraphNode node={node({ lastLine: "thinking", streaming: true })} selected={false} onPointerDown={vi.fn()} onSelect={vi.fn()} />
    );
    expect(container.querySelector(".ar-caret")).not.toBeNull();
    rerender(
      <GraphNode node={node({ lastLine: "done", streaming: false })} selected={false} onPointerDown={vi.fn()} onSelect={vi.fn()} />
    );
    expect(container.querySelector(".ar-caret")).toBeNull();
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `npx vitest run components/__tests__/graph-node.test.tsx`
Expected: FAIL — `Cannot find module '@/components/graph-node'`.

- [ ] **Step 5: Implement the node**

`web/components/graph-node.tsx`:
```tsx
"use client";

import { RewardChart } from "@/components/metric-chart";
import type { SimNode } from "@/hooks/use-force-graph";
import { STATUS_HEX } from "@/lib/status-colors";
import { cn } from "@/lib/utils";

const NODE_W = 168;

/** A draggable graph node showing live status, streaming line, and reward spark. */
export function GraphNode({
  node,
  selected,
  onPointerDown,
  onSelect,
}: {
  node: SimNode;
  selected: boolean;
  onPointerDown: (e: React.PointerEvent) => void;
  onSelect: () => void;
}) {
  const color = STATUS_HEX[node.status];
  const running = node.status === "running";
  const hasCurve = (node.rewards?.length ?? 0) > 1;

  return (
    <div
      role="button"
      tabIndex={0}
      onPointerDown={(e) => {
        e.stopPropagation();
        onPointerDown(e);
      }}
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect()}
      style={{
        left: node.x,
        top: node.y,
        width: node.isRoot ? NODE_W + 24 : NODE_W,
      }}
      className={cn(
        "absolute -translate-x-1/2 -translate-y-1/2 cursor-grab touch-none select-none rounded-xl border bg-canvas-card px-3 py-2.5 shadow-lg transition-[border-color,box-shadow] active:cursor-grabbing",
        "motion-safe:animate-[ar-node-in_240ms_ease-out]",
        selected ? "border-sunset" : "border-hairline hover:border-canvas-mid"
      )}
    >
      <div className="flex items-center gap-2">
        <span className="relative inline-flex size-2.5 shrink-0">
          {running && (
            <span
              aria-hidden
              className="ar-node-pulse absolute inset-0 rounded-full"
              style={{ background: color }}
            />
          )}
          <span
            aria-hidden
            className="relative inline-flex size-2.5 rounded-full"
            style={{ background: color }}
          />
        </span>
        <span className="truncate text-[13px] text-ink">{node.label}</span>
        <span className="ml-auto shrink-0 truncate text-[10px] uppercase tracking-wider text-mute">
          {node.kind}
        </span>
      </div>

      {(node.lastLine || node.streaming) && (
        <p className="mt-1.5 line-clamp-2 text-[11px] leading-snug text-body">
          {node.lastLine}
          {node.streaming && (
            <span
              aria-hidden
              className="ar-caret ml-0.5 inline-block h-3 w-1 -translate-y-px align-middle bg-sunset"
            />
          )}
        </p>
      )}

      {node.reward != null && (
        <div className="mt-1 text-[11px] text-mute">
          reward {node.reward.toFixed(3)}
        </div>
      )}
      {hasCurve && (
        <div className="mt-1 h-6">
          <RewardChart points={node.rewards} height={24} spark />
        </div>
      )}
    </div>
  );
}
```
Add the node-enter keyframe to the `@layer utilities` block in `globals.css`:
```css
  @keyframes ar-node-in { from { opacity: 0; transform: translate(-50%, -50%) scale(0.8); } to { opacity: 1; transform: translate(-50%, -50%) scale(1); } }
```

- [ ] **Step 6: Run test + the full reducer/agent-tree regression**

Run: `npx vitest run components/__tests__/graph-node.test.tsx`
Expected: PASS (2 tests).
Run: `npx vitest run components/__tests__/states.test.tsx`
Expected: PASS (agent-tree still renders with the shared `STATUS_HEX`).
Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add web/lib/status-colors.ts web/components/agent-tree.tsx web/components/graph-node.tsx web/components/__tests__/graph-node.test.tsx web/app/globals.css
git commit -m "feat(web): live graph node + shared status palette + keyframes"
```

---

### Task 6: Animated edge + full-screen graph overlay

**Files:**
- Create: `web/components/graph-edge.tsx`
- Create: `web/components/agent-graph.tsx`
- Create: `web/components/__tests__/agent-graph.test.tsx`

**Interfaces:**
- Consumes: `useForceGraph`/`SimNode` (Task 3), `usePanZoom` (Task 4), `GraphNode` component (Task 5), `GraphLink` (Task 2), `STATUS_HEX`.
- Produces: `<GraphEdge from={SimNode} to={SimNode} active={boolean} />`.
- Produces: `<AgentGraph graph={{ nodes: GraphNode[]; links: GraphLink[] }} goal={string} onClose={() => void} />`.

- [ ] **Step 1: Implement the edge**

`web/components/graph-edge.tsx`:
```tsx
import type { SimNode } from "@/hooks/use-force-graph";

/** A parent→child curved edge; when active, a flowing dash conveys live SSE. */
export function GraphEdge({
  from,
  to,
  active,
}: {
  from: SimNode;
  to: SimNode;
  active: boolean;
}) {
  const d = `M ${from.x} ${from.y} C ${from.x} ${(from.y + to.y) / 2}, ${to.x} ${
    (from.y + to.y) / 2
  }, ${to.x} ${to.y}`;
  return (
    <g>
      <path d={d} fill="none" stroke="#2a2e35" strokeWidth={1.5} />
      {active && (
        <path
          className="ar-edge-flow"
          d={d}
          fill="none"
          stroke="#ff7a17"
          strokeWidth={1.5}
          opacity={0.9}
        />
      )}
    </g>
  );
}
```

- [ ] **Step 2: Write the failing test**

`web/components/__tests__/agent-graph.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeAll, afterEach } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

beforeAll(() => {
  if (!("ResizeObserver" in globalThis)) {
    globalThis.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  }
});
afterEach(() => cleanup());

import { AgentGraph } from "@/components/agent-graph";
import type { GraphNode, GraphLink } from "@/lib/types";

const NODES: GraphNode[] = [
  { id: "root", label: "Main agent", kind: "Research", status: "running", depth: 0, isRoot: true, rewards: [] },
  { id: "c1", label: "A", kind: "tune lr", status: "running", depth: 1, isRoot: false, rewards: [] },
];
const LINKS: GraphLink[] = [{ source: "root", target: "c1", active: true }];

describe("AgentGraph", () => {
  it("renders one button per node (close + each agent)", () => {
    render(<AgentGraph graph={{ nodes: NODES, links: LINKS }} goal="Improve PPO" onClose={vi.fn()} />);
    expect(screen.getByText("Main agent")).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText(/Improve PPO/)).toBeInTheDocument();
  });

  it("calls onClose on Escape and on the close button", () => {
    const onClose = vi.fn();
    render(<AgentGraph graph={{ nodes: NODES, links: LINKS }} goal="g" onClose={onClose} />);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: /close graph/i }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npx vitest run components/__tests__/agent-graph.test.tsx`
Expected: FAIL — `Cannot find module '@/components/agent-graph'`.

- [ ] **Step 4: Implement the overlay**

`web/components/agent-graph.tsx`:
```tsx
"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { X } from "lucide-react";

import { GraphEdge } from "@/components/graph-edge";
import { GraphNode } from "@/components/graph-node";
import { Button } from "@/components/ui/button";
import { useForceGraph, type SimNode } from "@/hooks/use-force-graph";
import { fitView, usePanZoom } from "@/hooks/use-pan-zoom";
import type { GraphLink, GraphNode as GraphNodeData } from "@/lib/types";

export function AgentGraph({
  graph,
  goal,
  onClose,
}: {
  graph: { nodes: GraphNodeData[]; links: GraphLink[] };
  goal: string;
  onClose: () => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 1200, height: 800 });
  const [selected, setSelected] = useState<string | null>(null);

  // Measure the viewport so the simulation centers correctly.
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setSize({ width: el.clientWidth, height: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { nodes, links, pin, release } = useForceGraph(graph, size);
  const { transform, setTransform, onWheel, onPointerDown, onPointerMove, onPointerUp } =
    usePanZoom();

  // Esc closes.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const dragging = useRef<string | null>(null);

  const fit = () => {
    if (!nodes.length) return;
    const xs = nodes.map((n) => n.x);
    const ys = nodes.map((n) => n.y);
    setTransform(
      fitView(
        { minX: Math.min(...xs), minY: Math.min(...ys), maxX: Math.max(...xs), maxY: Math.max(...ys) },
        size
      )
    );
  };

  function startNodeDrag(id: string, e: React.PointerEvent) {
    dragging.current = id;
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  }
  function moveNodeDrag(e: React.PointerEvent) {
    const id = dragging.current;
    if (!id) return;
    const rect = containerRef.current!.getBoundingClientRect();
    const x = (e.clientX - rect.left - transform.x) / transform.k;
    const y = (e.clientY - rect.top - transform.y) / transform.k;
    pin(id, x, y);
  }
  function endNodeDrag() {
    if (dragging.current) release(dragging.current);
    dragging.current = null;
  }

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-canvas/95 backdrop-blur-sm">
      <header className="flex items-center gap-3 border-b border-hairline px-4 py-3">
        <span className="text-[13px] text-ink">Agent graph</span>
        <span className="truncate text-[12px] text-mute">{goal}</span>
        <span className="ml-auto text-[11px] text-mute">{nodes.length} nodes</span>
        <Button variant="ghost" size="sm" onClick={fit} aria-label="Fit to view">
          Fit
        </Button>
        <Button variant="ghost" size="icon" className="size-8" aria-label="Close graph" onClick={onClose}>
          <X className="size-4" />
        </Button>
      </header>

      <div
        ref={containerRef}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={(e) => {
          onPointerMove(e);
          moveNodeDrag(e);
        }}
        onPointerUp={(e) => {
          onPointerUp();
          endNodeDrag();
        }}
        className="relative min-h-0 flex-1 touch-none overflow-hidden [background:radial-gradient(60%_60%_at_50%_40%,#12141a_0%,#0a0a0a_100%)]"
      >
        <div
          className="absolute inset-0 origin-top-left"
          style={{ transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.k})` }}
        >
          <svg className="absolute inset-0 h-full w-full overflow-visible" aria-hidden>
            {links.map((l) => {
              const from = byId.get(l.source as string);
              const to = byId.get(l.target as string);
              if (!from || !to) return null;
              return <GraphEdge key={`${l.source}->${l.target}`} from={from} to={to} active={l.active} />;
            })}
          </svg>
          {nodes.map((n: SimNode) => (
            <GraphNode
              key={n.id}
              node={n}
              selected={selected === n.id}
              onPointerDown={(e) => startNodeDrag(n.id, e)}
              onSelect={() => setSelected(n.id)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest run components/__tests__/agent-graph.test.tsx`
Expected: PASS (2 tests). (The d3 simulation ticks via `setNodes`; initial render already shows nodes from the reconcile-on-mount `setNodes([...merged])`.)
Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add web/components/graph-edge.tsx web/components/agent-graph.tsx web/components/__tests__/agent-graph.test.tsx
git commit -m "feat(web): full-screen force-graph overlay with animated edges"
```

---

### Task 7: Wire the overlay into the app + final verification

**Files:**
- Modify: `web/components/tree-panel.tsx` (make the tree a clickable "expand" button; add `onExpand` prop)
- Modify: `web/components/__tests__/states.test.tsx` (assert the expand affordance fires)
- Modify: `web/app/page.tsx` (add `graphOpen` state; pass `onExpand`; render `<AgentGraph>`)

**Interfaces:**
- Consumes: `AgentGraph` (Task 6), `graphOf` (Task 2).
- Produces: `TreePanel` gains optional `onExpand?: () => void`.

- [ ] **Step 1: Write the failing test**

In `web/components/__tests__/states.test.tsx`, add to the `TreePanel states` describe block (import `fireEvent` and `vi` at the top — `vi` is already imported; add `fireEvent` to the `@testing-library/react` import):
```tsx
  it("fires onExpand when the tree is clicked", () => {
    const onExpand = vi.fn();
    const tree = { id: "root", label: "Main agent", status: "running" as const, children: [] };
    render(<TreePanel tree={tree} subagents={[]} artifacts={[]} onExpand={onExpand} />);
    fireEvent.click(screen.getByRole("button", { name: /expand agent graph/i }));
    expect(onExpand).toHaveBeenCalledTimes(1);
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run components/__tests__/states.test.tsx -t "fires onExpand"`
Expected: FAIL — no button with that accessible name (and `onExpand` is not a prop yet).

- [ ] **Step 3: Make the tree clickable in TreePanel**

In `web/components/tree-panel.tsx`:
1. Add `onExpand` to the prop type: `onExpand?: () => void;`.
2. Replace the tree container `<div … >{tree ? <AgentTree root={tree} /> : …}</div>` with a button when `onExpand` and `tree` are present:
```tsx
{tree ? (
  <button
    type="button"
    onClick={onExpand}
    aria-label="Expand agent graph"
    className="group flex min-h-[120px] w-full items-center justify-center rounded-lg border border-hairline bg-canvas-card/40 px-3 py-4 transition-colors hover:border-canvas-mid focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
  >
    <AgentTree root={tree} />
  </button>
) : (
  <div className="flex min-h-[120px] items-center justify-center rounded-lg border border-hairline bg-canvas-card/40 px-3 py-4">
    <span className="text-[12px] text-mute">No agents yet.</span>
  </div>
)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run components/__tests__/states.test.tsx`
Expected: PASS (existing TreePanel test + new onExpand test).

- [ ] **Step 5: Wire `graphOpen` + overlay into the page**

In `web/app/page.tsx`:
1. Add imports:
```tsx
import { AgentGraph } from "@/components/agent-graph";
```
and add `graphOf` to the existing import from `@/lib/session-reducer`.
2. Add state near the others: `const [graphOpen, setGraphOpen] = useState(false);`.
3. Derive the graph next to `const tree = treeOf(state);`: `const graph = graphOf(state);`.
4. Pass `onExpand` to the right-rail `TreePanel`:
```tsx
const rightRail = (
  <TreePanel
    tree={tree}
    subagents={subagents}
    artifacts={artifacts}
    onExpand={() => setGraphOpen(true)}
  />
);
```
5. Render the overlay just before the closing `</TooltipProvider>`:
```tsx
{graphOpen && (
  <AgentGraph graph={graph} goal={state.goal} onClose={() => setGraphOpen(false)} />
)}
```
6. In `select(...)`, also close the graph on session switch: add `setGraphOpen(false);` next to `setTreeOpen(false);`.

- [ ] **Step 6: Full verification**

Run: `npx vitest run`
Expected: ALL tests pass (existing + new from Tasks 1–7).
Run: `npx tsc --noEmit`
Expected: no errors.
Run: `npx eslint .`
Expected: no new errors.

- [ ] **Step 7: Manual smoke (preview)**

Start the dev server and confirm in the browser preview:
1. Drag the divider between the sidebar and main pane — the sidebar widens/narrows and the width survives a reload (localStorage). Double-click the divider resets it.
2. Open a session with subagents → the right-rail tree is now clickable → opens the full-screen graph.
3. Nodes float/settle (physics), drag a node and it pins + the graph jiggles, wheel zooms, background drag pans.
4. A running node shows the pulsing ring + streaming line/caret; active edges show the flowing dash; reward sparkline renders.
5. Esc and the close button dismiss the overlay.

Capture a screenshot of the open graph as proof.

- [ ] **Step 8: Commit**

```bash
git add web/components/tree-panel.tsx web/components/__tests__/states.test.tsx web/app/page.tsx
git commit -m "feat(web): open force-graph overlay from the right-rail tree"
```

---

## Self-Review

**Spec coverage:**
- Resizable sidebar (200–480, persisted, reset) → Task 1. ✓
- `graphOf` + `lastLine`/`streaming` stamping → Task 2. ✓
- d3-force sim + reconcile-by-id → Task 3. ✓
- Pan/zoom (drag bg, wheel, fit) → Task 4. ✓
- Live node (pulse, caret, sparkline) + shared `STATUS_HEX` → Task 5. ✓
- Animated edge flow + full-screen overlay (Esc/close) → Task 6. ✓
- Clickable tree entry point + page wiring → Task 7. ✓
- `prefers-reduced-motion` gating → Task 5 (globals.css). ✓
- Token/log never create a job (invariant) → Task 2 test `orphan.order === []`. ✓
- Tests mirror existing patterns (`globals:false` imports, `env()`/`reduce()`, `renderHook`, ResizeObserver polyfill). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every test step shows the assertions and the exact run command + expected result.

**Type consistency:** `SimNode` (Task 3) is reused verbatim by `GraphNode`/`AgentGraph` (Tasks 5–6). `GraphNode`/`GraphLink` (Task 2) flow into `useForceGraph`/`graphOf`. `Transform` (Task 4) is internal to pan/zoom. `STATUS_HEX` (Task 5) is consumed by `GraphNode`, `agent-tree`, and `GraphEdge`'s hardcoded `#ff7a17` (sunset, matches the palette). `onExpand` added in Task 7 matches the `TreePanel` call site.

**Out of scope (unchanged from spec):** right-rail resize, persisted node positions, minimap, 3D.
