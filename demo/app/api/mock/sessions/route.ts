import { NextResponse } from "next/server";

import { createMockSession, listMockSessions } from "@/lib/sim/store";

export const dynamic = "force-dynamic";

/** POST /api/mock/sessions — create a session from a goal (free-interactive). */
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const goal = String(body.goal ?? "").trim();
  const userId = String(body.user_id ?? "demo") || "demo";
  if (!goal) {
    return NextResponse.json({ error: "goal required" }, { status: 400 });
  }
  return NextResponse.json(createMockSession(goal, userId));
}

/** GET /api/mock/sessions?user_id=demo — the sidebar session list. */
export async function GET(req: Request) {
  const userId = new URL(req.url).searchParams.get("user_id") ?? "demo";
  return NextResponse.json(listMockSessions(userId));
}
