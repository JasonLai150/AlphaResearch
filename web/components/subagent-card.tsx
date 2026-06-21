import { RewardChart } from "@/components/metric-chart";
import { StatusDot, STATUS_LABEL } from "@/components/status-dot";
import type { Subagent } from "@/lib/types";
import { cn } from "@/lib/utils";

/*
  Border-only on the canvas (no fill) so the muted reward/status text keeps a
  passing contrast ratio — `mute` on the lighter card fill lands just under AA.
  When `onSelect` is provided the whole card becomes a button that opens the
  sub-agent's live console.
*/
export function SubagentCard({
  agent,
  onSelect,
}: {
  agent: Subagent;
  onSelect?: () => void;
}) {
  const hasCurve = (agent.rewards?.length ?? 0) > 1;
  return (
    <div
      {...(onSelect
        ? {
            role: "button" as const,
            tabIndex: 0,
            onClick: onSelect,
            onKeyDown: (e: React.KeyboardEvent) =>
              (e.key === "Enter" || e.key === " ") &&
              (e.preventDefault(), onSelect()),
            "aria-label": `Open ${agent.name} console`,
          }
        : {})}
      className={cn(
        "flex flex-col gap-2 rounded-lg border border-hairline px-3 py-2.5 transition-colors hover:border-canvas-mid",
        onSelect &&
          "cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      )}
    >
      <div className="flex items-center gap-3">
        <StatusDot status={agent.status} />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] text-ink">
            {agent.name} · {agent.kind}
          </div>
          <div className="truncate text-[11px] text-mute">
            {agent.reward != null
              ? `reward ${agent.reward.toFixed(3)}`
              : agent.note}
          </div>
        </div>
        <span className="shrink-0 font-mono text-[11px] uppercase tracking-wider text-mute">
          {STATUS_LABEL[agent.status]}
        </span>
      </div>
      {hasCurve && (
        <div className="h-7">
          <RewardChart points={agent.rewards!} height={28} spark />
        </div>
      )}
    </div>
  );
}
