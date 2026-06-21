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
      onPointerCancel={onPointerUp}
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
