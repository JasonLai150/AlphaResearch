"use client";

import { useCallback, useRef, useState } from "react";

export interface Transform {
  x: number;
  y: number;
  k: number;
}

const DEFAULT_BOUNDS: [number, number] = [0.25, 3];

/** Zoom by `factor` while keeping the world point under `cursor` fixed. */
export function zoomAt(
  t: Transform,
  cursor: { x: number; y: number },
  factor: number,
  bounds: [number, number] = DEFAULT_BOUNDS
): Transform {
  const k = Math.min(bounds[1], Math.max(bounds[0], t.k * factor));
  const scale = k / t.k;
  return {
    k,
    x: cursor.x - (cursor.x - t.x) * scale,
    y: cursor.y - (cursor.y - t.y) * scale,
  };
}

/** Compute a transform that fits `content` bounds inside `viewport`. */
export function fitView(
  content: { minX: number; minY: number; maxX: number; maxY: number },
  viewport: { width: number; height: number },
  padding = 80,
  bounds: [number, number] = DEFAULT_BOUNDS
): Transform {
  const cw = Math.max(content.maxX - content.minX, 1);
  const ch = Math.max(content.maxY - content.minY, 1);
  const k = Math.min(
    bounds[1],
    Math.max(
      bounds[0],
      Math.min(
        (Math.max(0, viewport.width - padding * 2)) / cw,
        (Math.max(0, viewport.height - padding * 2)) / ch
      )
    )
  );
  const cx = (content.minX + content.maxX) / 2;
  const cy = (content.minY + content.maxY) / 2;
  return { k, x: viewport.width / 2 - cx * k, y: viewport.height / 2 - cy * k };
}

export function usePanZoom(initial: Transform = { x: 0, y: 0, k: 1 }) {
  const [transform, setTransform] = useState<Transform>(initial);
  const panning = useRef<{ x: number; y: number } | null>(null);

  // NOTE for consumers: React attaches wheel listeners passively, so this
  // handler cannot preventDefault the page scroll. The consuming element should
  // sit in a full-screen overlay (no page scroll behind it) and/or set
  // `overscroll-behavior: contain` to avoid the page scrolling under the zoom.
  const onWheel = useCallback((e: React.WheelEvent) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const cursor = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
    setTransform((t) => zoomAt(t, cursor, factor));
  }, []);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    // Only pan when the background itself is grabbed (nodes stop propagation).
    if (e.target !== e.currentTarget) return;
    panning.current = { x: e.clientX, y: e.clientY };
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const p = panning.current;
    if (!p) return;
    const dx = e.clientX - p.x;
    const dy = e.clientY - p.y;
    panning.current = { x: e.clientX, y: e.clientY };
    setTransform((t) => ({ ...t, x: t.x + dx, y: t.y + dy }));
  }, []);

  const onPointerUp = useCallback((e?: React.PointerEvent) => {
    panning.current = null;
    if (e && e.currentTarget.hasPointerCapture?.(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
  }, []);

  const reset = useCallback(() => setTransform(initial), [initial]);

  return { transform, setTransform, onWheel, onPointerDown, onPointerMove, onPointerUp, onPointerCancel: onPointerUp, reset };
}
