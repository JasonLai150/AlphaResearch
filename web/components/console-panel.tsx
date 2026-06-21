"use client";

import { useCallback, useEffect, useRef } from "react";

import { ScrollArea } from "@/components/ui/scroll-area";
import type { ConsoleLine } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Raw operational console (stdout/stderr) for one agent — the output that used
 * to only reach the Cloud Run / Modal logs. Monospace, auto-following the tail
 * unless the user has scrolled up. stderr lines are tinted so failures stand out.
 */
export function ConsolePanel({
  lines,
  className,
}: {
  lines: ConsoleLine[];
  className?: string;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const atBottomRef = useRef(true);

  const getViewport = useCallback(
    () =>
      rootRef.current?.querySelector<HTMLDivElement>(
        "[data-radix-scroll-area-viewport]"
      ) ?? null,
    []
  );

  useEffect(() => {
    const viewport = getViewport();
    if (!viewport) return;
    const onScroll = () => {
      const distance =
        viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
      atBottomRef.current = distance <= 40;
    };
    onScroll();
    viewport.addEventListener("scroll", onScroll, { passive: true });
    return () => viewport.removeEventListener("scroll", onScroll);
  }, [getViewport]);

  // Follow the tail on new output only when already pinned to the bottom.
  useEffect(() => {
    if (atBottomRef.current) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [lines.length]);

  return (
    <div ref={rootRef} className={cn("relative flex min-h-0 flex-1 flex-col", className)}>
      <ScrollArea className="min-h-0 flex-1">
        <div
          role="log"
          aria-live="polite"
          aria-relevant="additions"
          aria-label="Agent console output"
          className="flex flex-col px-4 py-3 font-mono text-[12px] leading-relaxed"
        >
          {lines.length === 0 ? (
            <p className="font-sans text-[13px] text-mute">No console output yet.</p>
          ) : (
            lines.map((l) => (
              <div
                key={l.id}
                data-stream={l.stream}
                className={cn(
                  "whitespace-pre-wrap break-words",
                  l.stream === "stderr" ? "text-amber-300/90" : "text-body"
                )}
              >
                {l.line}
              </div>
            ))
          )}
          <div ref={bottomRef} />
        </div>
      </ScrollArea>
    </div>
  );
}
