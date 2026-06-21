import { NextResponse } from "next/server";

import { getMockSession } from "@/lib/sim/store";
import { sessionMetrics } from "@/lib/sim/researcher";

export const dynamic = "force-dynamic";

/*
  GET /api/mock/sessions/{sid}/metrics — all researchers' revealed training
  curves (reward / loss / efficiency), for the in-chat long-term graphs overlay.
*/
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ sid: string }> }
) {
  const { sid } = await params;
  const s = getMockSession(sid);
  if (!s) return NextResponse.json({ error: "session not found" }, { status: 404 });
  return NextResponse.json(sessionMetrics(s));
}
