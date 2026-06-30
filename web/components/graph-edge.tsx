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
