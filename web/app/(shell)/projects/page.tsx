"use client";

import Link from "next/link";

import { useShellSessions } from "@/components/app-shell";
import { Eyebrow } from "@/components/eyebrow";
import { PageHeader } from "@/components/page-header";
import { SessionRow } from "@/components/session-row";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { groupByMode } from "@/lib/session-stats";

export default function ProjectsPage() {
  const { sessions, loading } = useShellSessions();
  const groups = groupByMode(sessions);
  const firstLoad = loading && sessions.length === 0;
  const empty = !loading && sessions.length === 0;

  return (
    <>
      <PageHeader
        eyebrow="Projects"
        title="Projects"
        description="Your research sessions, grouped by mode."
      />
      <div className="flex flex-col gap-8 px-6 py-6">
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
              No projects yet — sessions you start are grouped here by mode.
            </p>
            <Button asChild variant="outline" size="sm">
              <Link href="/">Start a research session</Link>
            </Button>
          </div>
        ) : (
          groups.map((g) => (
            <section key={g.mode} className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <Eyebrow as="h2">{g.mode}</Eyebrow>
                <Badge variant="outline" className="text-[10px]">
                  {g.sessions.length}
                </Badge>
              </div>
              <div className="flex flex-col gap-2">
                {g.sessions.map((s) => (
                  <SessionRow key={s.id} session={s} />
                ))}
              </div>
            </section>
          ))
        )}
      </div>
    </>
  );
}
