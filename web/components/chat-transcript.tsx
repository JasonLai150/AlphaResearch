"use client";

import { useEffect, useRef } from "react";
import { Loader2 } from "lucide-react";

import { Eyebrow } from "@/components/eyebrow";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { TranscriptItem } from "@/lib/types";

const AUTHOR: Record<TranscriptItem["role"], string> = {
  user: "You",
  assistant: "Lead agent",
  tool: "Tool",
  system: "System",
};

/** The research conversation — user prompts, lead-agent turns, tool lines. */
export function ChatTranscript({
  items,
  running,
}: {
  items: TranscriptItem[];
  running?: boolean;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [items.length, running]);

  return (
    <ScrollArea className="min-h-0 flex-1">
      <div className="mx-auto flex max-w-3xl flex-col gap-7 px-4 py-8 md:px-6">
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
                </p>
              )}
            </article>
          );
        })}

        {running && (
          <div className="inline-flex w-fit items-center gap-2 rounded-full border border-hairline px-3 py-1 text-xs text-body">
            <Loader2 className="size-3.5 animate-spin text-sunset" aria-hidden />
            Working…
          </div>
        )}

        {!items.length && !running && (
          <p className="text-[14px] text-mute">No messages yet.</p>
        )}

        <div ref={bottomRef} />
      </div>
    </ScrollArea>
  );
}
