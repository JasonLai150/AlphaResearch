"use client";

import { useEffect, useState } from "react";

import { fetchFullSession, streamSession } from "@/lib/api";
import { applyEvent, emptyState } from "@/lib/session-reducer";
import type { ConnPhase, SessionState } from "@/lib/types";

/**
 * Subscribe to a session's live event stream and fold it into view state.
 * Pass `null` for no active session; `getToken` supplies the API auth token.
 */
export function useSession(
  sessionId: string | null,
  getToken?: () => Promise<string | undefined>
) {
  const [state, setState] = useState<SessionState>(() => emptyState(sessionId));
  const [phase, setPhase] = useState<ConnPhase>("idle");

  useEffect(() => {
    if (!sessionId) {
      setState(emptyState(null));
      setPhase("idle");
      return;
    }
    let cancelled = false;
    setState(emptyState(sessionId));
    setPhase("connecting");

    // Grab the goal quickly; the stream (replayed from the start) rebuilds the rest.
    (async () => {
      const token = getToken ? await getToken() : undefined;
      try {
        const full = await fetchFullSession(sessionId, token);
        if (!cancelled && full.session) {
          setState((s) => ({ ...s, goal: full.session!.goal }));
        }
      } catch {
        /* ignore */
      }
    })();

    const handle = streamSession(sessionId, {
      getToken,
      onEvent: (env) => {
        if (!cancelled) setState((s) => applyEvent(s, env));
      },
      onPhase: (p) => {
        if (!cancelled) setPhase(p);
      },
    });

    return () => {
      cancelled = true;
      handle.close();
    };
    // getToken identity may change per render; we intentionally only re-subscribe
    // when the session id changes (token is fetched fresh per connect).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  return { state, phase };
}
