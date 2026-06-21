import { assembleEvents, getMockSession } from "@/lib/sim/store";

export const dynamic = "force-dynamic";
// Node runtime (not edge) so the long-lived stream + timers behave predictably.
export const runtime = "nodejs";

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/*
  GET /api/mock/sessions/{sid}/stream — the dummy SSE server. Walks the session's
  wall-clock timeline and emits real EventEnvelope frames, sleeping until each
  event's scheduled time so the run unfolds slowly + incrementally. Events whose
  time has already passed (history sessions, or catch-up after a reconnect) flush
  immediately. Honors Last-Event-ID so the copied streamSession resume logic
  works unchanged. Stays open after the run to pick up follow-up turns.
*/
export async function GET(
  req: Request,
  { params }: { params: Promise<{ sid: string }> }
) {
  const { sid } = await params;
  const session = getMockSession(sid);
  if (!session) return new Response("session not found", { status: 404 });

  const lastId = req.headers.get("Last-Event-ID");
  const startCursor = lastId ? parseInt(lastId, 10) + 1 : 0;

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      let aborted = false;
      const onAbort = () => {
        aborted = true;
      };
      req.signal.addEventListener("abort", onAbort);

      const send = (id: number, data: unknown) =>
        controller.enqueue(
          encoder.encode(`id: ${id}\ndata: ${JSON.stringify(data)}\n\n`)
        );
      const heartbeat = () => controller.enqueue(encoder.encode(`: keep-alive\n\n`));

      let cursor = Number.isFinite(startCursor) ? Math.max(0, startCursor) : 0;
      let idle = 0;
      try {
        while (!aborted) {
          const events = assembleEvents(session);
          while (cursor < events.length && !aborted) {
            const ev = events[cursor];
            const dueAt = session.createdAtMs + ev.tMs;
            const wait = dueAt - Date.now();
            if (wait > 0) {
              // Sleep in short slices so client aborts are noticed promptly.
              await sleep(Math.min(wait, 500));
              if (Date.now() < dueAt) continue; // still early — keep waiting
            }
            send(cursor, { ...ev.env, v: 1 });
            cursor++;
            idle = 0;
          }
          if (aborted) break;
          // Caught up: idle-poll so follow-up turns (new events) get picked up.
          await sleep(700);
          if (++idle % 12 === 0) heartbeat(); // ~every 8s
        }
      } catch {
        /* controller closed / client gone */
      } finally {
        req.signal.removeEventListener("abort", onAbort);
        try {
          controller.close();
        } catch {
          /* already closed */
        }
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
