"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, fetchFullSession, streamSession } from "@/lib/api";
import type { SseHandle } from "@/lib/api";
import { applyEvent, emptyState } from "@/lib/session-reducer";
import type { ConnPhase, SessionState } from "@/lib/types";

/**
 * Subscribe to a session's live event stream and fold it into view state.
 * Pass `null` for no active session; `getToken` supplies the API auth token.
 *
 * Returns `{ state, phase, error, notFound, reconnect }`:
 *  - `error`     — human message on a fetch/stream auth (or hard) failure.
 *  - `notFound`  — true when the session is missing (fetch 404 / null session).
 *  - `reconnect` — forces the stream to re-subscribe immediately.
 */
export function useSession(
  sessionId: string | null,
  getToken?: () => Promise<string | undefined>
) {
  const [state, setState] = useState<SessionState>(() => emptyState(sessionId));
  const [phase, setPhase] = useState<ConnPhase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const handleRef = useRef<SseHandle | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setState(emptyState(null));
      setPhase("idle");
      setError(null);
      setNotFound(false);
      handleRef.current = null;
      return;
    }
    let cancelled = false;
    setState(emptyState(sessionId));
    setPhase("connecting");
    setError(null);
    setNotFound(false);

    // Grab the goal/startedAt quickly; the stream (replayed from the start)
    // rebuilds the rest. A 404 (or null session) marks the session not-found
    // and stops the infinite "connecting" spinner.
    (async () => {
      const token = getToken ? await getToken() : undefined;
      try {
        const full = await fetchFullSession(sessionId, token);
        if (cancelled) return;
        if (!full.session) {
          setNotFound(true);
          setPhase("closed");
          handleRef.current?.close();
          handleRef.current = null;
          return;
        }
        setState((s) => ({
          ...s,
          goal: full.session!.goal,
          startedAt: full.session!.created_at,
          mode: full.session!.mode ?? s.mode,
          // Seed loop state on resume so round/status render before the stream
          // replays the round_started/loop_stopped events.
          loop: full.loop
            ? {
                round: full.loop.rounds.length || 1,
                maxRounds: full.loop.max_rounds,
                goalMetric: full.loop.goal_metric,
                status: full.loop.status,
                reason: full.loop.stop_reason || undefined,
              }
            : s.loop,
        }));
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 404) {
          setNotFound(true);
          setPhase("closed");
          handleRef.current?.close();
          handleRef.current = null;
          return;
        }
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
          setError("You're not authorized to view this session.");
          setPhase("error");
          return;
        }
        // Transient fetch failure — the stream still drives the connection.
        setError("Couldn't load session details.");
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
      onAuthError: (status) => {
        if (!cancelled) {
          setError(
            status === 401
              ? "Your session expired. Please sign in again."
              : "You're not authorized to view this session."
          );
        }
      },
    });
    handleRef.current = handle;

    return () => {
      cancelled = true;
      handle.close();
      handleRef.current = null;
    };
    // getToken identity may change per render; we intentionally only re-subscribe
    // when the session id changes (token is fetched fresh per connect).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const reconnect = useCallback(() => {
    setError(null);
    handleRef.current?.reconnect();
  }, []);

  return { state, phase, error, notFound, reconnect };
}
