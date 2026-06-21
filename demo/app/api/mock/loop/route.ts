import { NextResponse } from "next/server";

import { createMockLoop, listMockLoops } from "@/lib/sim/loop-store";

export const dynamic = "force-dynamic";

/** POST /api/mock/loop — start an autonomous loop. */
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const goal = String(body.goal ?? "").trim();
  const maxRounds = Math.max(1, Math.min(12, Number(body.max_rounds ?? 6)));
  const goalMetric = Math.max(0.05, Math.min(0.99, Number(body.goal_metric ?? 0.9)));
  if (!goal) return NextResponse.json({ error: "goal required" }, { status: 400 });
  return NextResponse.json(createMockLoop(goal, maxRounds, goalMetric));
}

/** GET /api/mock/loop?user_id=demo — list loops (autonomous page history). */
export async function GET(req: Request) {
  const userId = new URL(req.url).searchParams.get("user_id") ?? "demo";
  return NextResponse.json(listMockLoops(userId));
}
