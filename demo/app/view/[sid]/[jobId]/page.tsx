"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { Loader2 } from "lucide-react";

import { MetricGrid } from "@/components/researcher-view/metric-grid";
import { OutputsGallery } from "@/components/researcher-view/outputs-gallery";
import { ResearcherHeader } from "@/components/researcher-view/researcher-header";
import { ToolTimeline } from "@/components/researcher-view/tool-timeline";
import { WorkLog } from "@/components/researcher-view/work-log";
import { useResearcher } from "@/hooks/use-researcher";

/*
  /view/{sid}/{jobId} — the GUI for one simulated sub-agent researcher. Reached
  by clicking a sub-agent in the chat's right rail. Shows the researcher's live
  work log, tool-call timeline, three long-term training curves (reward / loss /
  efficiency), and its mocked outputs (reward plot, sample rollout).
*/
export default function ResearcherViewPage() {
  const params = useParams<{ sid: string; jobId: string }>();
  const sid = params.sid;
  const jobId = params.jobId;
  const { detail, loading, notFound } = useResearcher(sid, jobId);

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas text-mute">
        <Loader2 className="size-5 animate-spin text-sunset" aria-hidden />
      </div>
    );
  }

  if (notFound || !detail) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-canvas px-6 text-center">
        <p className="text-sm text-mute">That researcher doesn&apos;t exist.</p>
        <Link
          href={`/app?s=${sid}`}
          className="rounded-full border border-hairline px-4 py-2 text-sm text-body hover:text-ink"
        >
          ← Back to chat
        </Link>
      </div>
    );
  }

  const live = ["running", "queued", "pending"].includes(detail.status);
  const progress = detail.totalPoints ? detail.points.length / detail.totalPoints : 0;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-canvas text-ink">
      <ResearcherHeader detail={detail} />
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6 md:px-6">
          {detail.summary && (
            <p className="rounded-xl border border-hairline bg-canvas-card px-4 py-3 text-[14px] leading-relaxed text-body">
              {detail.summary}
            </p>
          )}

          <MetricGrid points={detail.points} metricName={detail.metricName} />

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.4fr_1fr]">
            <div className="flex min-h-[320px] flex-col">
              <WorkLog lines={detail.workLog} live={live} />
            </div>
            <div className="flex flex-col gap-6">
              <ToolTimeline tools={detail.tools} progress={progress} />
              <OutputsGallery artifacts={detail.artifacts} />
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
