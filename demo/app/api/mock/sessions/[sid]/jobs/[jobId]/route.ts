import { NextResponse } from "next/server";

import { getMockSession } from "@/lib/sim/store";
import { researcherDetail } from "@/lib/sim/researcher";

export const dynamic = "force-dynamic";

/*
  GET /api/mock/sessions/{sid}/jobs/{jobId} — rich detail for one researcher,
  consumed by the /view inspector. Curve points + work-log are revealed up to
  the current time so an in-flight researcher shows partial progress.
*/
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ sid: string; jobId: string }> }
) {
  const { sid, jobId } = await params;
  const s = getMockSession(sid);
  if (!s) return NextResponse.json({ error: "session not found" }, { status: 404 });
  const detail = researcherDetail(s, jobId);
  if (!detail) return NextResponse.json({ error: "researcher not found" }, { status: 404 });
  return NextResponse.json(detail);
}
