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
  // Stub rAF so the d3 sim doesn't tick asynchronously during the test
  // (prevents setNodes calls outside React's act() and suppresses act() warnings).
  globalThis.requestAnimationFrame = (() => 0) as unknown as typeof requestAnimationFrame;
  globalThis.cancelAnimationFrame = (() => {}) as unknown as typeof cancelAnimationFrame;
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
