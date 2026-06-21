"use client";

import { useEffect, useState } from "react";

import type { ResearcherDetail } from "@/lib/sim/researcher";

/*
  Fetch a single researcher's detail from the mock API and poll while it's still
  running, so the /view inspector grows incrementally (curves, work-log) the same
  way the chat does. Polling stops once the researcher reaches a terminal state.
*/
export function useResearcher(sid: string, jobId: string) {
  const [detail, setDetail] = useState<ResearcherDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function tick() {
      try {
        const res = await fetch(`/api/mock/sessions/${sid}/jobs/${jobId}`, {
          cache: "no-store",
        });
        if (cancelled) return;
        if (res.status === 404) {
          setNotFound(true);
          setLoading(false);
          return;
        }
        const d = (await res.json()) as ResearcherDetail;
        if (cancelled) return;
        setDetail(d);
        setLoading(false);
        if (["running", "queued", "pending"].includes(d.status)) {
          timer = setTimeout(tick, 1200);
        }
      } catch {
        if (!cancelled) timer = setTimeout(tick, 2000);
      }
    }

    setLoading(true);
    setNotFound(false);
    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [sid, jobId]);

  return { detail, loading, notFound };
}
