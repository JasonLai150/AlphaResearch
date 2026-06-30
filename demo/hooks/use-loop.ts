"use client";

import { useCallback, useEffect, useState } from "react";

import type { LiveLoop } from "@/lib/sim/loop-store";

/** Poll a single autonomous loop while it's running (rounds tick in slowly). */
export function useLoop(lid: string | null) {
  const [loop, setLoop] = useState<LiveLoop | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!lid) {
      setLoop(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    setLoading(true);
    async function tick() {
      try {
        const res = await fetch(`/api/mock/loop/${lid}`, { cache: "no-store" });
        if (cancelled) return;
        if (res.ok) {
          const l = (await res.json()) as LiveLoop;
          if (cancelled) return;
          setLoop(l);
          if (l.status === "running") timer = setTimeout(tick, 900);
        }
      } catch {
        if (!cancelled) timer = setTimeout(tick, 1800);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [lid]);

  return { loop, loading };
}

/** The user's loops (history list), polled periodically. */
export function useLoops(userId: string) {
  const [loops, setLoops] = useState<LiveLoop[]>([]);
  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`/api/mock/loop?user_id=${encodeURIComponent(userId)}`, {
        cache: "no-store",
      });
      if (res.ok) setLoops((await res.json()) as LiveLoop[]);
    } catch {
      /* keep last-known */
    }
  }, [userId]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  return { loops, refresh };
}
