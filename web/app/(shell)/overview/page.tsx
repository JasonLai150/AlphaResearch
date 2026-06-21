"use client";

import Link from "next/link";

import { useShellSessions } from "@/components/app-shell";
import { Eyebrow } from "@/components/eyebrow";
import { PageHeader } from "@/components/page-header";
import { SessionRow } from "@/components/session-row";
import { Button } from "@/components/ui/button";
import { recent, summarize } from "@/lib/session-stats";
import { cn } from "@/lib/utils";

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: string;
}) {
  return (
    <div className="flex flex-col gap-1 rounded-xl border border-hairline bg-canvas-card px-5 py-4">
      <span className={cn("text-3xl tracking-[-0.02em] text-ink", accent)}>
        {value}
      </span>
      <span className="text-[13px] text-mute">{label}</span>
    </div>
  );
}

export default function OverviewPage() {
  const { sessions, loading } = useShellSessions();
  const stats = summarize(sessions);
  const latest = recent(sessions, 8);
  const firstLoad = loading && sessions.length === 0;
  const empty = !loading && sessions.length === 0;

  return (
    <>
      <PageHeader
        eyebrow="Overview"
        title="Research overview"
        description="Every research session you've started, at a glance."
      />
      <div className="flex flex-col gap-8 px-6 py-6">
        <section
          aria-label="Session statistics"
          className="grid grid-cols-2 gap-3 sm:grid-cols-4"
        >
          <StatCard label="Total sessions" value={stats.total} />
          <StatCard label="Running" value={stats.running} accent="text-sunset" />
          <StatCard label="Completed" value={stats.done} />
          <StatCard
            label="Failed"
            value={stats.failed}
            accent={stats.failed ? "text-destructive" : undefined}
          />
        </section>

        <section className="flex flex-col gap-3">
          <Eyebrow as="h2">Recent sessions</Eyebrow>
          {firstLoad ? (
            <div className="flex flex-col gap-2" aria-hidden>
              {Array.from({ length: 4 }).map((_, i) => (
                <div
                  key={i}
                  className="h-[50px] animate-pulse rounded-lg border border-hairline bg-canvas-card"
                />
              ))}
            </div>
          ) : empty ? (
            <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-hairline px-6 py-12 text-center">
              <p className="text-sm text-mute">
                No research sessions yet — start one to see it here.
              </p>
              <Button asChild variant="outline" size="sm">
                <Link href="/">Start a research session</Link>
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              {latest.map((s) => (
                <SessionRow key={s.id} session={s} />
              ))}
            </div>
          )}
        </section>
      </div>
    </>
  );
}
