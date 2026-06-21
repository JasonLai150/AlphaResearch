"use client";

import { Loader2 } from "lucide-react";

import { RoundCard } from "@/components/autonomous/round-card";
import { Eyebrow } from "@/components/eyebrow";
import type { LiveLoop } from "@/lib/sim/loop-store";

const PHASE_LABEL: Record<string, string> = {
  planning: "Planning the round",
  dispatching: "Dispatching sub-agents",
  synthesizing: "Synthesizing results",
};

/** The ordered list of completed rounds + the round currently in progress. */
export function RoundTimeline({ loop }: { loop: LiveLoop }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <Eyebrow as="h2">Rounds</Eyebrow>
        <span className="text-[11px] text-mute">
          {loop.rounds.length} completed
          {loop.status === "running" ? " · running" : ""}
        </span>
      </div>

      {loop.rounds.length === 0 && !loop.current && (
        <div className="rounded-xl border border-dashed border-hairline px-4 py-10 text-center text-[13px] text-mute">
          The first round is being planned…
        </div>
      )}

      {loop.rounds.map((r) => (
        <RoundCard key={r.round_index} round={r} metricName={loop.metricName} />
      ))}

      {loop.current && (
        <div className="flex flex-col gap-2 rounded-xl border border-sunset/40 bg-sunset/5 p-4">
          <div className="flex items-center gap-3">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-sunset/50 font-mono text-[12px] text-sunset">
              {loop.current.round_index + 1}
            </span>
            <span className="flex flex-1 items-center gap-2 text-[13px] text-body">
              <Loader2 className="size-3.5 animate-spin text-sunset" aria-hidden />
              {PHASE_LABEL[loop.current.phase] ?? "Working"}…
            </span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-canvas-soft">
            <div
              className="h-full rounded-full bg-sunset transition-[width] duration-700"
              style={{ width: `${Math.round(loop.current.progress * 100)}%` }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
