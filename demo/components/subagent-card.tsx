import Link from "next/link";
import { ArrowUpRight } from "lucide-react";

import { RewardChart } from "@/components/metric-chart";
import { StatusDot, STATUS_LABEL } from "@/components/status-dot";
import { cn } from "@/lib/utils";
import type { Subagent } from "@/lib/types";

/*
  Border-only on the canvas (no fill) so the muted reward/status text keeps a
  passing contrast ratio — `mute` on the lighter card fill lands just under AA.
  When `sessionId` is supplied the whole card becomes a link into the /view
  researcher inspector for this sub-agent.
*/
export function SubagentCard({
  agent,
  sessionId,
}: {
  agent: Subagent;
  sessionId?: string | null;
}) {
  const hasCurve = (agent.rewards?.length ?? 0) > 1;
  const body = (
    <>
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
        {sessionId && (
          <ArrowUpRight
            className="size-3.5 shrink-0 text-mute transition-colors group-hover:text-sunset"
            aria-hidden
          />
        )}
        <span className="shrink-0 font-mono text-[11px] uppercase tracking-wider text-mute">
          {STATUS_LABEL[agent.status]}
        </span>
      </div>
      {hasCurve && (
        <div className="h-7">
          <RewardChart points={agent.rewards!} height={28} spark />
        </div>
      )}
    </>
  );

  const className = cn(
    "flex flex-col gap-2 rounded-lg border border-hairline px-3 py-2.5 transition-colors hover:border-canvas-mid",
    sessionId &&
      "group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
  );

  if (sessionId) {
    return (
      <Link
        href={`/view/${sessionId}/${agent.id}`}
        className={className}
        aria-label={`Open researcher ${agent.name} — ${agent.kind}`}
      >
        {body}
      </Link>
    );
  }
  return <div className={className}>{body}</div>;
}
