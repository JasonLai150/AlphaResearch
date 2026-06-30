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
