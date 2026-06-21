"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown, Loader2 } from "lucide-react";

import { Eyebrow } from "@/components/eyebrow";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { TranscriptItem } from "@/lib/types";

const AUTHOR: Record<TranscriptItem["role"], string> = {
  user: "You",
  assistant: "Lead agent",
  tool: "Tool",
  system: "System",
};

/** Px from the bottom within which we still consider the user "at the bottom". */
const NEAR_BOTTOM_THRESHOLD = 80;

/** The research conversation — user prompts, lead-agent turns, tool lines. */
export function ChatTranscript({
  items,
  running,
}: {
  items: TranscriptItem[];
  running?: boolean;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  // Whether the user is pinned near the bottom; when false we never yank them
  // down and instead surface the "Jump to latest" pill.
  const atBottomRef = useRef(true);
  const [showJump, setShowJump] = useState(false);

  // The actual scroll container is the Radix viewport inside ScrollArea.
  const getViewport = useCallback(
    () =>
      rootRef.current?.querySelector<HTMLDivElement>(
        "[data-radix-scroll-area-viewport]"
      ) ?? null,
    []
  );

  const scrollToBottom = useCallback(
    (behavior: ScrollBehavior = "auto") => {
      bottomRef.current?.scrollIntoView({ block: "end", behavior });
    },
    []
  );

  // Track scroll position so auto-scroll only kicks in when already at bottom.
  useEffect(() => {
    const viewport = getViewport();
    if (!viewport) return;

    const onScroll = () => {
      const distance =
        viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
      const atBottom = distance <= NEAR_BOTTOM_THRESHOLD;
      atBottomRef.current = atBottom;
      setShowJump(!atBottom);
    };

    onScroll();
    viewport.addEventListener("scroll", onScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", onScroll);
  }, [getViewport]);

  // New content or a status change: only follow if the user is at the bottom.
  useEffect(() => {
    if (atBottomRef.current) {
      scrollToBottom();
      setShowJump(false);
    }
  }, [items.length, running, scrollToBottom]);

  const onJump = useCallback(() => {
    scrollToBottom("smooth");
    atBottomRef.current = true;
    setShowJump(false);
  }, [scrollToBottom]);

  return (
    <div ref={rootRef} className="relative flex min-h-0 flex-1 flex-col">
      <ScrollArea className="min-h-0 flex-1">
        <div
          role="log"
          aria-live="polite"
          aria-relevant="additions"
          aria-label="Conversation transcript"
          className="mx-auto flex max-w-3xl flex-col gap-7 px-4 py-8 md:px-6"
        >
          {items.map((m) => {
            if (m.role === "tool") {
              return (
                <div
                  key={m.id}
                  className="flex items-center gap-2 font-mono text-[12px] text-mute"
                >
                  <span className="text-sunset" aria-hidden>
                    ↳
                  </span>
                  {m.toolName ? `used ${m.toolName}` : m.text}
                </div>
              );
            }
            if (m.role === "system") {
              return (
                <div key={m.id} className="text-center text-[12px] text-mute">
                  {m.text}
                </div>
              );
            }
            return (
              <article key={m.id} className="flex flex-col gap-2.5">
                <Eyebrow>{AUTHOR[m.role]}</Eyebrow>
                {m.role === "user" ? (
                  <div className="self-start whitespace-pre-wrap rounded-lg border border-hairline bg-canvas-card px-4 py-3 text-[15px] leading-relaxed text-body">
                    {m.text}
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-body">
                    {m.text}
                    {m.streaming && (
                      <span
                        data-testid="stream-caret"
                        aria-hidden
                        className="ml-0.5 inline-block h-[1.1em] w-[2px] translate-y-[0.15em] animate-pulse bg-sunset"
                      />
                    )}
                  </p>
                )}
              </article>
            );
          })}

          {running && (
            <div
              role="status"
              aria-label="Lead agent is working"
              className="inline-flex w-fit items-center gap-2 rounded-full border border-hairline px-3 py-1 text-xs text-body"
            >
              <Loader2
                className="size-3.5 animate-spin text-sunset"
                aria-hidden
              />
              Working…
            </div>
          )}

          {!items.length && !running && (
            <p className="text-[14px] text-mute">No messages yet.</p>
          )}

          <div ref={bottomRef} />
        </div>
      </ScrollArea>

      {showJump && (
        <button
          type="button"
          onClick={onJump}
          className="absolute bottom-4 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-hairline bg-canvas-card px-3 py-1.5 text-xs text-body shadow-sm transition-colors hover:bg-canvas-soft hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowDown className="size-3.5 text-sunset" aria-hidden />
          Jump to latest
        </button>
      )}
    </div>
  );
}
