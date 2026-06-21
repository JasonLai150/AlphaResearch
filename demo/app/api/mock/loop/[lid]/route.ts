import { NextResponse } from "next/server";

import { getMockLoop, liveLoop } from "@/lib/sim/loop-store";

export const dynamic = "force-dynamic";

/** GET /api/mock/loop/{lid} — the live loop doc (polled by the autonomous page). */
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ lid: string }> }
) {
  const { lid } = await params;
  const l = getMockLoop(lid);
  if (!l) return NextResponse.json({ error: "loop not found" }, { status: 404 });
  return NextResponse.json(liveLoop(l));
}
