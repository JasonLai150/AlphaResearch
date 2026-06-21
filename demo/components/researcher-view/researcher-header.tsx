"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { StatusDot, STATUS_LABEL } from "@/components/status-dot";
import type { ResearcherDetail } from "@/lib/sim/researcher";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] uppercase tracking-wider text-mute">{label}</span>
      <span className="font-mono text-[13px] text-ink">{value}</span>
    </div>
  );
}

export function ResearcherHeader({ detail }: { detail: ResearcherDetail }) {
  const final =
    detail.finalReward != null ? detail.finalReward.toFixed(3) : "—";
  return (
    <header className="border-b border-hairline bg-canvas">
      <div className="flex items-center gap-3 px-4 py-3 md:px-6">
        <Link
          href={`/app?s=${detail.sid}`}
          aria-label="Back to chat"
          className="flex size-8 items-center justify-center rounded-lg border border-hairline text-mute transition-colors hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowLeft className="size-4" />
        </Link>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <StatusDot status={detail.status} />
            <h1 className="truncate text-[15px] text-ink">
              Researcher {detail.label} · {detail.kind}
            </h1>
          </div>
          <p className="truncate text-[12px] text-mute">{detail.blurb}</p>
        </div>
        <span className="shrink-0 rounded-full border border-hairline px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider text-mute">
          {STATUS_LABEL[detail.status]}
        </span>
      </div>
      <div className="flex flex-wrap gap-x-8 gap-y-3 border-t border-hairline px-4 py-3 md:px-6">
        <Stat label="Env" value={detail.env} />
        <Stat label="Algorithm" value={detail.algo} />
        <Stat label="Steps" value={`${(detail.steps / 1000).toFixed(0)}k`} />
        <Stat label="Seeds" value={String(detail.seeds)} />
        <Stat label="Baseline" value={detail.baseline.toFixed(2)} />
        <Stat label={detail.metricName} value={final} />
      </div>
    </header>
  );
}
