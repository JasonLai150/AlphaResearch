"use client";

import { useCallback, useEffect, useState } from "react";

export function clampWidth(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n));
}

/**
 * Persisted, clamped width for a draggable pane. SSR-safe: the first render
 * uses `initial` (so server and client markup match); any stored width is read
 * from localStorage in an effect after mount.
 */
export function useResizablePane(opts: {
  key: string;
  min: number;
  max: number;
  initial: number;
}) {
  const { key, min, max, initial } = opts;
  const [width, setWidthState] = useState(initial);

  useEffect(() => {
    const stored = localStorage.getItem(key);
    if (stored != null) {
      const n = Number(stored);
      if (!Number.isNaN(n)) setWidthState(clampWidth(n, min, max));
    }
  }, [key, min, max]);

  const setWidth = useCallback(
    (n: number) => {
      const w = clampWidth(n, min, max);
      setWidthState(w);
      localStorage.setItem(key, String(w));
    },
    [key, min, max]
  );

  const reset = useCallback(() => {
    setWidthState(initial);
    localStorage.removeItem(key);
  }, [key, initial]);

  return { width, setWidth, reset };
}
