import { NextResponse } from "next/server";

import { getMockSession } from "@/lib/sim/store";
import { jobIdFor } from "@/lib/sim/timeline";
import type { FullSession } from "@/lib/types";

export const dynamic = "force-dynamic";

/*
  GET /api/mock/sessions/{sid}/full — a minimal snapshot. The client only reads
  session.goal / created_at / mode here; the SSE stream (replayed from the
  start) rebuilds jobs/transcript/artifacts via the reducer. A missing session
  returns { session: null } so the UI marks it not-found.
*/
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ sid: string }> }
) {
  const { sid } = await params;
  const s = getMockSession(sid);
  const empty: FullSession = {
    session: null,
    jobs: [],
    runs: [],
    tree: {},
    transcript: [],
    artifacts: [],
  };
  if (!s) return NextResponse.json(empty, { status: 404 });
  return NextResponse.json({
    ...empty,
    session: {
      id: s.id,
      user_id: s.userId,
      goal: s.goal,
      mode: s.mode,
      status: "running",
      created_at: new Date(s.createdAtMs).toISOString(),
      root_job_id: jobIdFor(s.id, "root"),
    },
  } satisfies FullSession);
}
