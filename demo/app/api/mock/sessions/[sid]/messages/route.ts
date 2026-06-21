import { NextResponse } from "next/server";

import { addTurn, getMockSession } from "@/lib/sim/store";

export const dynamic = "force-dynamic";

/*
  POST /api/mock/sessions/{sid}/messages — a follow-up turn. Appends the user
  message + a generated lead reply to the session timeline; the already-open SSE
  stream picks it up on its next poll. Returns { queued } like the real API.
*/
export async function POST(
  req: Request,
  { params }: { params: Promise<{ sid: string }> }
) {
  const { sid } = await params;
  if (!getMockSession(sid)) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  const body = await req.json().catch(() => ({}));
  const content = String(body.content ?? "");
  return NextResponse.json({ queued: addTurn(sid, content) });
}
