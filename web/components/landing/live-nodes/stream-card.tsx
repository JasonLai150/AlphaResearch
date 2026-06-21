"use client";

import { useEffect, useState } from "react";

import { useReducedMotion } from "@/hooks/use-reduced-motion";

/*
  A live node rendered as an SSE token feed. Lines type out character by
  character (variable cadence, like tokens arriving), the completed lines scroll,
  and it loops. Under reduced-motion it shows a settled frame with no typing.
*/
export function StreamCard({
  agentId,
  lines,
  delayMs = 0,
}: {
  agentId: string;
  lines: string[];
  delayMs?: number;
}) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState<string[]>([]);
  const [typing, setTyping] = useState("");

  useEffect(() => {
    if (reduced) {
      setShown(lines.slice(-2));
      setTyping(lines[lines.length - 1] ?? "");
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let li = 0;
    let ci = 0;
    let buffer: string[] = [];

    const tick = () => {
      if (cancelled) return;
      const line = lines[li % lines.length];
      ci += 1;
      setTyping(line.slice(0, ci));
      if (ci >= line.length) {
        buffer = [...buffer, line].slice(-2);
        setShown(buffer);
        setTyping("");
        li += 1;
        ci = 0;
        timer = setTimeout(tick, 820);
      } else {
        timer = setTimeout(tick, 24 + (ci % 5) * 9);
      }
    };
    timer = setTimeout(tick, delayMs);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [reduced, lines, delayMs]);

  return (
    <div className="w-[14rem] overflow-hidden rounded-lg border border-hairline bg-canvas-card/75 shadow-[0_8px_30px_rgba(0,0,0,0.45)] backdrop-blur-md">
      <div className="flex items-center gap-2 border-b border-hairline/70 px-3 py-2">
        <span className="size-1.5 rounded-full bg-sunset shadow-[0_0_8px_rgba(255,122,23,0.9)]" />
        <span className="font-mono text-[11px] tracking-tight text-body">{agentId}</span>
        <span className="ml-auto font-mono text-[10px] uppercase tracking-[0.12em] text-mute">
          sse
        </span>
      </div>
      <div className="flex h-[64px] flex-col justify-end gap-0.5 px-3 py-2">
        {shown.map((l, i) => (
          <p key={`${l}-${i}`} className="truncate font-mono text-[11px] leading-tight text-mute">
            {l}
          </p>
        ))}
        <p className="truncate font-mono text-[11px] leading-tight text-body">
          {typing}
          {!reduced && (
            <span className="ml-0.5 inline-block h-[0.85em] w-[2px] translate-y-[1px] animate-pulse bg-sunset align-middle" />
          )}
        </p>
      </div>
    </div>
  );
}
