"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { createSession, sendMessage, ApiError } from "@/lib/api";
import { getDefaultBudget } from "@/lib/settings-store";
import type { TranscriptItem } from "@/lib/types";

/** Autonomous-loop options carried from the composer for a brand-new session. */
export interface AutonomousOptions {
  mode?: "oneshot" | "autonomous";
  maxRounds?: number;
  goalMetric?: number;
}

/** Clear pending if no assistant reply lands within this window (#3). */
const PENDING_TIMEOUT_MS = 30_000;

function errMessage(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    if (e.status === 401) return "Your session expired. Please sign in again.";
    if (e.status === 403) return "You're not authorized to do that.";
    if (e.status === 404) return "Session not found.";
  }
  if (e instanceof Error && e.message) return e.message;
  return fallback;
}

/**
 * Owns the chat submit lifecycle for the page: busy/pending flags, the
 * optimistic user echo (#8), the no-response timeout (#3), and error
 * surfacing (#1/#23). The page merges `optimistic` into the live transcript
 * and reconciles it once the server echoes the message back.
 *
 * `onCreate(text)` is called for the first message of a brand-new session and
 * should return the new session id (so the page can select it).
 */
export function useChatSubmit({
  activeId,
  userId,
  getToken,
  onCreate,
}: {
  activeId: string | null;
  userId: string | null;
  getToken: () => Promise<string | undefined>;
  onCreate: (sessionId: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(false);
  const [optimistic, setOptimistic] = useState<TranscriptItem | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearTimer = useCallback(() => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Reset everything cleanly when switching sessions (#3).
  useEffect(() => {
    setPending(false);
    setOptimistic(null);
    clearTimer();
  }, [activeId, clearTimer]);

  useEffect(() => clearTimer, [clearTimer]);

  /** Stop the "working" indicator once the assistant has replied. */
  const settle = useCallback(() => {
    setPending(false);
    clearTimer();
  }, [clearTimer]);

  /** Drop the optimistic echo once the server transcript contains the message. */
  const reconcile = useCallback((serverHasIt: boolean) => {
    if (serverHasIt) setOptimistic(null);
  }, []);

  const onSubmit = useCallback(
    async (text: string, opts?: AutonomousOptions) => {
      setBusy(true);
      try {
        if (!activeId) {
          const token = await getToken();
          // Apply the user's saved default budget (Settings) if any; undefined
          // is omitted from the request so the backend default still applies.
          const { session_id } = await createSession(
            {
              userId: userId ?? "",
              goal: text,
              budget: getDefaultBudget(),
              mode: opts?.mode,
              maxRounds: opts?.maxRounds,
              goalMetric: opts?.goalMetric,
            },
            token
          );
          onCreate(session_id);
        } else {
          // Optimistically echo the user's message immediately (#8). The id is
          // local-only ("opt:") so it never collides with reducer ids ("t…").
          setOptimistic({ id: "opt:user", role: "user", text });
          setPending(true);
          // Arm the no-response timeout (#3).
          clearTimer();
          timerRef.current = setTimeout(() => {
            timerRef.current = null;
            setPending(false);
            toast.info("No response yet — you can retry.");
          }, PENDING_TIMEOUT_MS);

          const { queued } = await sendMessage(activeId, text, await getToken());
          // Empty / rejected message (#23): drop the echo, stop working.
          if (queued === false) {
            setOptimistic(null);
            settle();
            toast.info("Message was empty.");
          }
        }
      } catch (e) {
        // Surface the failure (#1) and drop the optimistic echo; the composer
        // restores the text because we re-throw.
        setOptimistic(null);
        settle();
        toast.error(errMessage(e, "Couldn't send your message."));
        throw e;
      } finally {
        setBusy(false);
      }
    },
    [activeId, userId, getToken, onCreate, clearTimer, settle]
  );

  return { busy, pending, optimistic, onSubmit, settle, reconcile };
}
