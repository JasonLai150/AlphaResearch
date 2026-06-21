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
  // Adjustment A: destructure onPointerCancel from usePanZoom.
  const { transform, setTransform, onWheel, onPointerDown, onPointerMove, onPointerUp, onPointerCancel } =
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
        // Adjustment A: pass the event to onPointerUp and add onPointerCancel handler.
        onPointerUp={(e) => { onPointerUp(e); endNodeDrag(); }}
        onPointerCancel={(e) => { onPointerCancel(e); endNodeDrag(); }}
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
