import { describe, expect, it } from "vitest";

import { buildAgentTree } from "@/lib/landing/graph";

describe("buildAgentTree", () => {
  it("produces a single root with no parent", () => {
    const { nodes } = buildAgentTree();
    const roots = nodes.filter((n) => n.depth === 0);
    expect(roots).toHaveLength(1);
    expect(roots[0].parent).toBeNull();
    expect(roots[0].kind).toBe("root");
    expect(roots[0].id).toBe("root");
  });

  it("is a tree: one edge per non-root node, every edge a real parent→child", () => {
    const { nodes, edges } = buildAgentTree();
    expect(edges).toHaveLength(nodes.length - 1);

    const byId = new Map(nodes.map((n) => [n.id, n]));
    for (const e of edges) {
      const child = byId.get(e.to);
      expect(child, `edge target ${e.to} exists`).toBeDefined();
      expect(child!.parent).toBe(e.from);
      expect(byId.has(e.from)).toBe(true);
    }
  });

  it("lays out within the unit square and respects maxDepth", () => {
    const { nodes } = buildAgentTree({ maxDepth: 3 });
    for (const n of nodes) {
      expect(n.depth).toBeGreaterThanOrEqual(0);
      expect(n.depth).toBeLessThanOrEqual(3);
      expect(n.x).toBeGreaterThanOrEqual(0);
      expect(n.x).toBeLessThanOrEqual(1);
      expect(n.y).toBeGreaterThanOrEqual(0);
      expect(n.y).toBeLessThanOrEqual(1);
    }
  });

  it("places deeper nodes further right (x grows with depth)", () => {
    const { nodes } = buildAgentTree();
    const root = nodes.find((n) => n.depth === 0)!;
    const deepest = nodes.reduce((a, b) => (b.depth > a.depth ? b : a));
    expect(deepest.x).toBeGreaterThan(root.x);
  });

  it("promotes stream and sim card nodes carrying their payloads", () => {
    const { nodes } = buildAgentTree();
    const streams = nodes.filter((n) => n.kind === "stream");
    const sims = nodes.filter((n) => n.kind === "sim");
    expect(streams.length).toBeGreaterThanOrEqual(1);
    expect(sims.length).toBeGreaterThanOrEqual(1);
    for (const s of streams) {
      expect(s.streamLines?.length).toBeTruthy();
      expect(typeof s.agentId).toBe("string");
    }
    for (const s of sims) {
      expect(s.sim === "reward" || s.sim === "grid").toBe(true);
      expect(typeof s.simLabel).toBe("string");
    }
  });

  it("is deterministic for a given seed", () => {
    expect(buildAgentTree({ seed: 7 })).toEqual(buildAgentTree({ seed: 7 }));
  });
});
