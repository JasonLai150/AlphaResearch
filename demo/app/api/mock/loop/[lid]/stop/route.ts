import { NextResponse } from "next/server";

import { requestStop } from "@/lib/sim/loop-store";

export const dynamic = "force-dynamic";

/*
  POST /api/mock/loop/{lid}/stop — request a user stop. The runner finalizes the
  loop as `stopped` at the next round boundary (matches autonomous-loops.md).
*/
export async function POST(
  _req: Request,
  { params }: { params: Promise<{ lid: string }> }
) {
  const { lid } = await params;
  return NextResponse.json({ stopped: requestStop(lid) });
}
