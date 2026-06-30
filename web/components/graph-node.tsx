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
