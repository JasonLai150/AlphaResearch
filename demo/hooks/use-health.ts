"use client";

import { useCallback, useEffect, useState } from "react";

import { API_BASE } from "@/lib/types";

export type HealthStatus = "checking" | "ok" | "down";

/**
 * Liveness of the backend API. Pings `GET /health` on mount and on an interval,
 * exposing a coarse reachable / unreachable status plus a manual recheck. This
 * is the only integration whose status the frontend can truly verify.
 */
export function useHealth(intervalMs = 15000) {
  const [status, setStatus] = useState<HealthStatus>("checking");

  const check = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
      setStatus(res.ok ? "ok" : "down");
    } catch {
      setStatus("down");
    }
  }, []);

  useEffect(() => {
    check();
    const timer = setInterval(check, intervalMs);
    return () => clearInterval(timer);
  }, [check, intervalMs]);

  return { status, recheck: check };
}
