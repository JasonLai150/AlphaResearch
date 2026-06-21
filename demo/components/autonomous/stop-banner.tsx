import { CheckCircle2, CircleSlash, Flag, OctagonX } from "lucide-react";

import { cn } from "@/lib/utils";
import type { LiveLoop } from "@/lib/sim/loop-store";

/** Terminal banner explaining why the loop ended (status + reason). */
export function StopBanner({ loop }: { loop: LiveLoop }) {
  if (loop.status === "running") return null;

  const goalReached = loop.status === "completed" && loop.stopReason === "goal_metric";
  const text =
    loop.stopReason === "goal_metric"
      ? `Goal reached — best ${loop.metricName} ${loop.bestMetric.toFixed(3)} cleared the ${loop.goalMetric.toFixed(2)} target.`
      : loop.stopReason === "plateau"
        ? `Stopped on plateau — no new best for ${loop.plateauK} consecutive rounds. Best ${loop.metricName} ${loop.bestMetric.toFixed(3)}.`
        : loop.stopReason === "max_rounds"
          ? `Reached the round budget (${loop.maxRounds} rounds). Best ${loop.metricName} ${loop.bestMetric.toFixed(3)}.`
          : loop.stopReason === "user"
            ? `Stopped by you after ${loop.rounds.length} round${loop.rounds.length === 1 ? "" : "s"}. Best ${loop.metricName} ${loop.bestMetric.toFixed(3)}.`
            : `Loop ${loop.status}.`;

  const Icon = goalReached
    ? CheckCircle2
    : loop.stopReason === "plateau"
      ? CircleSlash
      : loop.status === "stopped"
        ? OctagonX
        : Flag;

  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-xl border px-4 py-3",
        goalReached
          ? "border-sunset/40 bg-sunset/5"
          : "border-hairline bg-canvas-card"
      )}
    >
      <Icon className={cn("size-5 shrink-0", goalReached ? "text-sunset" : "text-mute")} aria-hidden />
      <div className="flex flex-col">
        <span className="text-[11px] uppercase tracking-wider text-mute">
          Loop {loop.status}
        </span>
        <span className="text-[14px] text-body">{text}</span>
      </div>
    </div>
  );
}
