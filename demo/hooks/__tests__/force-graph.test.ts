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

  it("preserves pin state (fx/fy) of existing nodes across a data refresh", () => {
    const prev: SimNode[] = [{ ...gn("p"), x: 10, y: 20, fx: 10, fy: 20 }];
    const out = reconcileNodes(prev, [gn("p", { status: "done" })], { x: 0, y: 0 });
    expect(out[0].fx).toBe(10);
    expect(out[0].fy).toBe(20);
    expect(out[0].status).toBe("done"); // data still refreshed
  });
});
