"use client";

import { useEffect, useState } from "react";
import { Infinity as InfinityIcon, OctagonX, Plus } from "lucide-react";
import { toast } from "sonner";

import { useAppAuth } from "@/components/auth/app-auth";
import { LoopComposer } from "@/components/autonomous/loop-composer";
import { LoopMetrics } from "@/components/autonomous/loop-metrics";
import { RoundTimeline } from "@/components/autonomous/round-timeline";
import { StopBanner } from "@/components/autonomous/stop-banner";
import { Eyebrow } from "@/components/eyebrow";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { useLoop, useLoops } from "@/hooks/use-loop";
import { cn, relativeTime } from "@/lib/utils";

const STATUS_TONE: Record<string, string> = {
  running: "text-sunset",
  completed: "text-sunset",
  stopped: "text-mute",
  budget_exhausted: "text-mute",
  failed: "text-destructive",
};

export default function AutonomousPage() {
  const { userId } = useAppAuth();
  const [activeId, setActiveId] = useState<string | null>(null);
  const { loop } = useLoop(activeId);
  const { loops, refresh } = useLoops(userId);

  // Restore / sync the active loop in the URL (?l=).
  useEffect(() => {
    const l = new URLSearchParams(window.location.search).get("l");
    if (l) setActiveId(l);
  }, []);

  function select(id: string | null) {
    setActiveId(id);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("l", id);
    else url.searchParams.delete("l");
    window.history.replaceState({}, "", url.toString());
  }

  async function stop() {
    if (!activeId) return;
    await fetch(`/api/mock/loop/${activeId}/stop`, { method: "POST" });
    toast.info("Stop requested — the loop finalizes at the next round boundary.");
  }

  return (
    <>
      <PageHeader
        eyebrow="Autonomous"
        title="Autonomous loops"
        description="Set a goal and a budget; the runner re-spawns research rounds on its own until the goal is met, the budget runs out, or progress plateaus."
      />

      <div className="flex flex-col gap-8 px-6 py-6">
        {!activeId || !loop ? (
          <>
            <LoopComposer
              onCreated={(id) => {
                select(id);
                refresh();
              }}
            />
            {loops.length > 0 && (
              <section className="flex flex-col gap-3">
                <Eyebrow as="h2">Recent loops</Eyebrow>
                <div className="flex flex-col gap-2">
                  {loops.map((l) => (
                    <button
                      key={l.id}
                      type="button"
                      onClick={() => select(l.id)}
                      className="flex items-center gap-3 rounded-lg border border-hairline px-4 py-3 text-left transition-colors hover:border-canvas-mid"
                    >
                      <InfinityIcon className="size-4 shrink-0 text-sunset" aria-hidden />
                      <span className="min-w-0 flex-1 truncate text-[13px] text-body">
                        {l.goal}
                      </span>
                      <span className="shrink-0 font-mono text-[11px] text-mute">
                        {l.rounds.length} rounds · best {l.bestMetric.toFixed(3)}
                      </span>
                      <span
                        className={cn(
                          "shrink-0 font-mono text-[11px] uppercase tracking-wider",
                          STATUS_TONE[l.status] ?? "text-mute"
                        )}
                      >
                        {l.status}
                      </span>
                      <span className="shrink-0 text-[11px] text-mute">
                        {relativeTime(l.createdAt)}
                      </span>
                    </button>
                  ))}
                </div>
              </section>
            )}
          </>
        ) : (
          <>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="flex min-w-0 flex-col gap-1">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "font-mono text-[11px] uppercase tracking-wider",
                      STATUS_TONE[loop.status] ?? "text-mute"
                    )}
                  >
                    ● {loop.status}
                  </span>
                  <span className="text-[11px] text-mute">
                    {loop.env} · {loop.algo} · target {loop.goalMetric.toFixed(2)}
                  </span>
                </div>
                <h2 className="max-w-2xl text-[16px] text-ink">{loop.goal}</h2>
              </div>
              <div className="flex shrink-0 gap-2">
                {loop.status === "running" && (
                  <Button variant="outline" size="sm" onClick={stop} className="rounded-full">
                    <OctagonX className="size-4" aria-hidden />
                    Stop loop
                  </Button>
                )}
                <Button variant="ghost" size="sm" onClick={() => select(null)} className="rounded-full">
                  <Plus className="size-4" aria-hidden />
                  New loop
                </Button>
              </div>
            </div>

            <StopBanner loop={loop} />
            <LoopMetrics loop={loop} />
            <RoundTimeline loop={loop} />
          </>
        )}
      </div>
    </>
  );
}
