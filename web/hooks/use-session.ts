"use client";

import { useEffect, useState } from "react";

import { fetchFullSession, streamSession } from "@/lib/api";
import { applyEvent, emptyState } from "@/lib/session-reducer";
import type { ConnPhase, SessionState } from "@/lib/types";

/**
 * Subscribe to a session's live event stream and fold it into view state.
 * Pass `null` for no active session.
 */
export function useSession(sessionId: string | null, token?: string) {
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
    fetchFullSession(sessionId, token)
      .then((full) => {
        if (!cancelled && full.session) {
          setState((s) => ({ ...s, goal: full.session!.goal }));
        }
      })
      .catch(() => {});

    const handle = streamSession(sessionId, {
      token,
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
  }, [sessionId, token]);

  return { state, phase };
}
