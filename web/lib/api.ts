import { API_BASE } from "@/lib/types";
import type {
  ConnPhase,
  EventEnvelope,
  FullSession,
  WireSession,
} from "@/lib/types";

/** Resolve an artifact URL — relative /artifacts/... paths are served by the API. */
export function artifactUrl(url: string): string {
  return url.startsWith("http") ? url : `${API_BASE}${url}`;
}

async function jsonFetch<T>(
  path: string,
  init?: RequestInit,
  token?: string
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    throw new Error(`${init?.method || "GET"} ${path} → ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function createSession(
  input: { userId: string; goal: string; budget?: number },
  token?: string
) {
  return jsonFetch<{ session_id: string; root_job_id: string }>(
    "/sessions",
    {
      method: "POST",
      body: JSON.stringify({
        user_id: input.userId,
        goal: input.goal,
        budget: input.budget,
      }),
    },
    token
  );
}

export function fetchFullSession(sid: string, token?: string) {
  return jsonFetch<FullSession>(`/sessions/${sid}/full`, undefined, token);
}

export function listSessions(userId: string, token?: string) {
  return jsonFetch<WireSession[]>(
    `/sessions?user_id=${encodeURIComponent(userId)}`,
    undefined,
    token
  );
}

/** Send a follow-up turn (multi-turn chat). */
export function sendMessage(sid: string, content: string, token?: string) {
  return jsonFetch<{ queued: boolean }>(
    `/sessions/${sid}/messages`,
    { method: "POST", body: JSON.stringify({ content }) },
    token
  );
}

export interface SseHandle {
  close(): void;
}

/*
  Fetch-based SSE client (EventSource can't set Authorization / Last-Event-ID
  headers). Replays from the start on first connect, resumes after the last id on
  reconnect, and auto-reconnects with a short backoff until close() is called.
*/
export function streamSession(
  sid: string,
  opts: {
    getToken?: () => Promise<string | undefined>;
    onEvent: (env: EventEnvelope) => void;
    onPhase?: (phase: ConnPhase) => void;
  }
): SseHandle {
  let closed = false;
  let lastId: string | null = null;
  let controller: AbortController | null = null;
  let fails = 0; // consecutive connect failures (reset once streaming)
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

  (async function loop() {
    while (!closed) {
      controller = new AbortController();
      try {
        opts.onPhase?.(lastId ? "reconnecting" : "connecting");
        // Fresh token per (re)connect so long-lived streams survive expiry.
        const token = opts.getToken ? await opts.getToken() : undefined;
        const headers: Record<string, string> = {};
        if (token) headers.Authorization = `Bearer ${token}`;
        if (lastId) headers["Last-Event-ID"] = lastId;
        const res = await fetch(`${API_BASE}/sessions/${sid}/stream`, {
          headers,
          signal: controller.signal,
          cache: "no-store",
        });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
        fails = 0;
        opts.onPhase?.("streaming");
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        // sse-starlette frames events with CRLF; tolerate both CRLF and LF.
        const FRAME = /\r\n\r\n|\n\n/;
        let buf = "";
        while (!closed) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let sep: RegExpExecArray | null;
          while ((sep = FRAME.exec(buf))) {
            const block = buf.slice(0, sep.index);
            buf = buf.slice(sep.index + sep[0].length);
            let id: string | undefined;
            let data = "";
            for (const line of block.split(/\r\n|\n/)) {
              if (line.startsWith("id:")) id = line.slice(3).trim();
              else if (line.startsWith("data:")) data += line.slice(5).trim();
            }
            if (id) lastId = id;
            if (data) {
              try {
                opts.onEvent(JSON.parse(data) as EventEnvelope);
              } catch {
                /* ignore malformed frame */
              }
            }
          }
        }
      } catch {
        if (closed) break;
        fails += 1;
      }
      if (closed) break;
      // Surface a real failure after a few tries (drives the "disconnected" UI),
      // and back off so we don't hammer a downed server.
      opts.onPhase?.(fails >= 3 ? "error" : "reconnecting");
      await sleep(Math.min(1500 * Math.max(fails, 1), 10000));
    }
    opts.onPhase?.("closed");
  })();

  return {
    close() {
      closed = true;
      controller?.abort();
    },
  };
}
