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
