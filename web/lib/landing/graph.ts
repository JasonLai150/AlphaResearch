/*
  Pure model for the landing hero's live agent tree. A root agent (the α) spawns
  sub-agents, which spawn sandboxed rollouts — a tidy left→right hierarchy
  (x = depth axis, y = cross axis, both normalized [0,1]). A handful of nodes are
  promoted to "card" kinds: `stream` nodes render a live SSE token feed, `sim`
  nodes render a mini RL simulation. Kept DOM/canvas-free so the layout and card
  assignment are deterministic and unit-testable.
*/

export type NodeKind = "root" | "agent" | "sandbox" | "stream" | "sim";

export interface TreeNode {
  id: string;
  depth: number; // 0 = root
  parent: string | null;
  x: number; // [0,1] — depth axis (left → right)
  y: number; // [0,1] — cross axis (top → bottom)
  kind: NodeKind;
  spawnOrder: number;
  // Card payloads — present only on the promoted card kinds.
  agentId?: string;
  streamLines?: string[];
  sim?: "reward" | "grid";
  simLabel?: string;
}

export interface TreeEdge {
  from: string;
  to: string;
  depth: number; // depth of the child endpoint — drives the reveal
  order: number;
}

export interface AgentTree {
  nodes: TreeNode[];
  edges: TreeEdge[];
  maxDepth: number;
}

export interface BuildTreeOptions {
  maxDepth?: number;
  rootBreadth?: number;
  seed?: number;
}

// Realistic-looking SSE feeds for the streaming cards (kept short to fit).
const STREAMS = [
  {
    id: "ppo·7f3a",
    lines: [
      "scope → sample-eff.",
      "spawn sandbox 0x1f",
      "rollout 2,304 steps",
      "reward 0.42 → 0.71 ▲",
      "kl 0.013 · ent 1.94",
      "checkpoint saved ✓",
    ],
  },
  {
    id: "sac·b1c0",
    lines: [
      "env DoorKey-8×8",
      "4 envs × 512 steps",
      "grad step 1,920",
      "actor loss 0.087 ↓",
      "eval success 0.83",
      "streaming results…",
    ],
  },
];

const SIMS: { id: string; sim: "reward" | "grid"; label: string }[] = [
  { id: "env·d8k", sim: "grid", label: "DoorKey-8×8" },
  { id: "eval·rwd", sim: "reward", label: "reward / ep" },
];

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Raw {
  id: string;
  depth: number;
  parent: string | null;
  children: Raw[];
  spawnOrder: number;
  y: number;
}

export function buildAgentTree(options: BuildTreeOptions = {}): AgentTree {
  const maxDepth = options.maxDepth ?? 3;
  const rootBreadth = options.rootBreadth ?? 4;
  const rng = mulberry32(options.seed ?? 0xa1fa);

  let spawnOrder = 0;
  const all: Raw[] = [];

  const breadthFor = (depth: number): number => {
    if (depth === 0) return rootBreadth;
    if (depth === 1) return 2 + Math.floor(rng() * 2); // 2–3
    return 1 + Math.floor(rng() * 2); // 1–2
  };

  function make(parent: Raw | null, depth: number): Raw {
    const node: Raw = {
      id: parent ? `${parent.id}-${spawnOrder}` : "root",
      depth,
      parent: parent ? parent.id : null,
      children: [],
      spawnOrder: spawnOrder++,
      y: 0,
    };
    all.push(node);
    if (depth < maxDepth) {
      const n = breadthFor(depth);
      for (let i = 0; i < n; i++) node.children.push(make(node, depth + 1));
    }
    return node;
  }
  const root = make(null, 0);

  // Tidy layout: leaves take sequential y slots; each parent centers on its kids.
  const leafCount = all.filter((n) => n.children.length === 0).length;
  let leaf = 0;
  function assignY(n: Raw): number {
    if (n.children.length === 0) {
      n.y = leafCount > 1 ? leaf / (leafCount - 1) : 0.5;
      leaf++;
      return n.y;
    }
    const ys = n.children.map(assignY);
    n.y = ys.reduce((a, b) => a + b, 0) / ys.length;
    return n.y;
  }
  assignY(root);

  const pad = 0.1;
  const mapX = (d: number) => (maxDepth === 0 ? 0.5 : pad + (d / maxDepth) * (1 - 2 * pad));
  const mapY = (y: number) => pad + y * (1 - 2 * pad);

  const nodes: TreeNode[] = all.map((n) => ({
    id: n.id,
    depth: n.depth,
    parent: n.parent,
    spawnOrder: n.spawnOrder,
    x: mapX(n.depth),
    y: mapY(n.y),
    kind: n.depth === 0 ? "root" : n.depth === 1 ? "agent" : "sandbox",
  }));

  const edges: TreeEdge[] = [];
  for (const n of all) {
    if (n.parent) edges.push({ from: n.parent, to: n.id, depth: n.depth, order: n.spawnOrder });
  }

  // Promote up to four well-separated mid-tree nodes to live cards (2 sim, 2
  // stream) so the streaming text and simulations have room to read.
  const candidates = nodes
    .filter((n) => n.depth >= 1 && n.depth <= Math.min(2, maxDepth))
    .sort((a, b) => a.y - b.y);
  // Pick the candidate nearest each of four vertical bands. This guarantees four
  // distinct, well-separated cards (≈0.24 apart) regardless of how the tree's
  // y-values cluster — index sampling left gaps and overlaps.
  const picks: TreeNode[] = [];
  const used = new Set<string>();
  for (const band of [0.14, 0.38, 0.62, 0.86]) {
    let best: TreeNode | null = null;
    let bestDist = Infinity;
    for (const c of candidates) {
      if (used.has(c.id)) continue;
      const d = Math.abs(c.y - band);
      if (d < bestDist) {
        bestDist = d;
        best = c;
      }
    }
    if (best) {
      picks.push(best);
      used.add(best.id);
    }
  }

  const kinds: NodeKind[] = ["sim", "stream", "stream", "sim"];
  let streamIdx = 0;
  let simIdx = 0;
  picks.forEach((p, i) => {
    p.kind = kinds[i % kinds.length];
    if (p.kind === "stream") {
      const s = STREAMS[streamIdx++ % STREAMS.length];
      p.agentId = s.id;
      p.streamLines = s.lines;
    } else {
      const m = SIMS[simIdx++ % SIMS.length];
      p.sim = m.sim;
      p.simLabel = m.label;
      p.agentId = m.id;
    }
  });

  return { nodes, edges, maxDepth };
}
