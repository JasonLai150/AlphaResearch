"use client";

import { useCallback, useEffect, useState } from "react";

import { ApiError, listSessions } from "@/lib/api";
import type { WireSession } from "@/lib/types";

/**
 * The user's session list (sidebar chat history). Polls every 8s so the sidebar
 * stays live; polling is cleared on unmount and paused while the tab is hidden.
 * Returns `{ sessions, loading, error, refresh }`.
 */
export function useSessions(
  userId: string | null,
  getToken?: () => Promise<string | undefined>
) {
  const [sessions, setSessions] = useState<WireSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const token = getToken ? await getToken() : undefined;
      setSessions(await listSessions(userId, token));
      setError(null);
    } catch (e) {
      // Keep last-known list on transient failure; only surface auth errors.
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        setError("Couldn't load your sessions — please sign in again.");
      } else {
        setError("Couldn't refresh sessions.");
      }
    } finally {
      setLoading(false);
    }
  }, [userId, getToken]);

  useEffect(() => {
    if (!userId) return;
    refresh();

    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (timer == null) timer = setInterval(refresh, 8000);
    };
    const stop = () => {
      if (timer != null) {
        clearInterval(timer);
        timer = null;
      }
    };
    const onVisibility = () => {
      if (document.hidden) stop();
      else {
        refresh();
        start();
      }
    };

    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [userId, refresh]);

  return { sessions, loading, error, refresh };
}
