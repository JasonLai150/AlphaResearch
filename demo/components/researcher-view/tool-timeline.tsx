"use client";

import { Check, Loader2, Wrench } from "lucide-react";

import { Eyebrow } from "@/components/eyebrow";
import { cn } from "@/lib/utils";

/*
  The researcher's tool-call timeline. `progress` (0–1) marks how far through the
  run we are; tools before that point read as done, the next as active, the rest
  pending — so the timeline advances live alongside the work log.
*/
export function ToolTimeline({
  tools,
  progress,
}: {
  tools: string[];
  progress: number;
}) {
  const activeIdx = Math.min(tools.length - 1, Math.floor(progress * tools.length));
  return (
    <div className="flex flex-col gap-2.5">
      <Eyebrow as="h3">Tool calls</Eyebrow>
      <ol className="flex flex-col">
        {tools.map((tool, i) => {
          const done = i < activeIdx || progress >= 1;
          const active = i === activeIdx && progress < 1;
          return (
            <li key={tool} className="flex items-center gap-3 py-1.5">
              <span
                className={cn(
                  "flex size-6 shrink-0 items-center justify-center rounded-full border",
                  done
                    ? "border-sunset/40 bg-sunset/10 text-sunset"
                    : active
                      ? "border-sunset text-sunset"
                      : "border-hairline text-mute"
                )}
              >
                {done ? (
                  <Check className="size-3.5" aria-hidden />
                ) : active ? (
                  <Loader2 className="size-3.5 animate-spin" aria-hidden />
                ) : (
                  <Wrench className="size-3 opacity-60" aria-hidden />
                )}
              </span>
              <span
                className={cn(
                  "font-mono text-[12px]",
                  done || active ? "text-body" : "text-mute"
                )}
              >
                {tool}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
