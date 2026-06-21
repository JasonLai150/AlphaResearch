"use client";

import { useEffect, useRef } from "react";

import { Eyebrow } from "@/components/eyebrow";

/*
  The researcher's live work log — its "thinking" + actions, terminal-styled.
  Lines arrive incrementally from polling; the latest line shows a caret while
  the researcher is still running.
*/
export function WorkLog({ lines, live }: { lines: string[]; live: boolean }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [lines.length]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-2.5">
      <Eyebrow as="h3">Work log</Eyebrow>
      <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-hairline bg-[#0f0f0f] p-3 font-mono text-[12px] leading-relaxed">
        {lines.length === 0 && <span className="text-mute">Waiting for the sandbox…</span>}
        {lines.map((line, i) => {
          const isLast = i === lines.length - 1;
          return (
            <div key={i} className="flex gap-2 py-0.5">
              <span className="shrink-0 select-none text-mute">{String(i + 1).padStart(2, "0")}</span>
              <span className="text-body">
                {line}
                {isLast && live && (
                  <span
                    aria-hidden
                    className="ml-0.5 inline-block h-3 w-1.5 -translate-y-px animate-pulse bg-sunset align-middle"
                  />
                )}
              </span>
            </div>
          );
        })}
        <div ref={endRef} />
      </div>
    </div>
  );
}
