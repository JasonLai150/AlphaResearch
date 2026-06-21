"use client";

import { useCallback, useEffect, useState } from "react";

import { listSessions } from "@/lib/api";
import type { WireSession } from "@/lib/types";

/** The user's session list (sidebar chat history), with a manual refresh. */
export function useSessions(
  userId: string | null,
  getToken?: () => Promise<string | undefined>
) {
  const [sessions, setSessions] = useState<WireSession[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const token = getToken ? await getToken() : undefined;
      setSessions(await listSessions(userId, token));
    } catch {
      /* keep last-known list on transient failure */
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { sessions, loading, refresh };
}
