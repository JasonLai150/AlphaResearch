import { ArrowUpRight, Minus } from "lucide-react";

import { cn } from "@/lib/utils";
import type { LoopRound } from "@/lib/sim/loop";

/** One completed round in the timeline. */
export function RoundCard({ round, metricName }: { round: LoopRound; metricName: string }) {
  const delta = round.best_metric - round.prev_best;
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-hairline bg-canvas-card p-4">
      <div className="flex items-center gap-3">
        <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-hairline font-mono text-[12px] text-mute">
          {round.round_index + 1}
        </span>
        <span className="flex-1 text-[13px] text-body">{round.plan}</span>
        <span
          className={cn(
            "flex shrink-0 items-center gap-1 font-mono text-[12px]",
            round.improved ? "text-sunset" : "text-mute"
          )}
        >
          {round.improved ? (
            <ArrowUpRight className="size-3.5" aria-hidden />
          ) : (
            <Minus className="size-3.5" aria-hidden />
          )}
          {round.best_metric.toFixed(3)}
          {round.improved && (
            <span className="text-[11px] text-mute">(+{delta.toFixed(3)})</span>
          )}
        </span>
      </div>
      <p className="text-[12px] leading-relaxed text-mute">{round.summary}</p>
      <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
        <span className="text-[11px] uppercase tracking-wider text-mute">runs</span>
        {round.sub_rewards.map((r, i) => (
          <span
            key={i}
            className="rounded-full border border-hairline px-2 py-0.5 font-mono text-[11px] text-body"
          >
            {r.toFixed(3)}
          </span>
        ))}
        <span className="ml-auto font-mono text-[11px] text-mute">
          best {metricName} {round.best_metric.toFixed(3)}
        </span>
      </div>
    </div>
  );
}
