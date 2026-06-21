import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, artifactUrl, streamSession } from "@/lib/api";
import type { EventEnvelope } from "@/lib/types";

// API_BASE in tests resolves to the default (no NEXT_PUBLIC_API_URL set).
const API_BASE = "http://localhost:8080";

/** Build a Response whose body streams the given byte chunks, then closes. */
function streamResponse(chunks: Uint8Array[], status = 200): Response {
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(c);
      controller.close();
    },
  });
  return new Response(body, { status });
}

/**
 * A Response body that never closes on its own. The returned `feed` pushes
 * bytes and `endStream` resolves the reader's `read()` with done. Lets a test
 * hold a connection open (so close()/reconnect() drive the loop, not EOF).
 */
function liveResponse(status = 200): {
  res: Response;
  feed: (s: string) => void;
  endStream: () => void;
} {
  let ctrl!: ReadableStreamDefaultController<Uint8Array>;
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      ctrl = controller;
    },
  });
  return {
    res: new Response(body, { status }),
    feed: (s: string) => ctrl.enqueue(enc.encode(s)),
    endStream: () => ctrl.close(),
  };
}

function bytes(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

/** Spin the microtask/macrotask queue so the async loop advances. */
async function flush(rounds = 4) {
  for (let i = 0; i < rounds; i++) {
    await Promise.resolve();
    await new Promise((r) => setTimeout(r, 0));
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("streamSession", () => {
  function env(id: string): string {
    return JSON.stringify({
      session_id: "s1",
      job_id: id,
      parent_job_id: null,
      depth: 0,
      type: "log",
      payload: { line: id },
      ts: "2026-06-21T00:00:00Z",
      v: 1,
    } satisfies EventEnvelope);
  }

  it("parses CRLF-framed SSE frames and calls onEvent with the envelope", async () => {
    const payload = env("j1");
    const fetchMock = vi.fn().mockResolvedValue(
      streamResponse([bytes(`id: 1\r\ndata: ${payload}\r\n\r\n`)])
    );
    vi.stubGlobal("fetch", fetchMock);

    const events: EventEnvelope[] = [];
    const handle = streamSession("s1", { onEvent: (e) => events.push(e) });
    await flush();
    handle.close();

    expect(events).toHaveLength(1);
    expect(events[0].job_id).toBe("j1");
    expect(events[0].payload.line).toBe("j1");
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/sessions/s1/stream`,
      expect.objectContaining({ cache: "no-store" })
    );
  });

  it("tolerates LF-only framing", async () => {
    const a = env("a");
    const b = env("b");
    const fetchMock = vi.fn().mockResolvedValue(
      // LF-only line endings AND LF-only frame separators.
      streamResponse([bytes(`id: 1\ndata: ${a}\n\nid: 2\ndata: ${b}\n\n`)])
    );
    vi.stubGlobal("fetch", fetchMock);

    const events: EventEnvelope[] = [];
    const handle = streamSession("s1", { onEvent: (e) => events.push(e) });
    await flush();
    handle.close();

    expect(events.map((e) => e.job_id)).toEqual(["a", "b"]);
  });

  it("handles a frame split across two read() chunks", async () => {
    const payload = env("split");
    const full = `id: 7\r\ndata: ${payload}\r\n\r\n`;
    const mid = Math.floor(full.length / 2);
    const fetchMock = vi.fn().mockResolvedValue(
      streamResponse([bytes(full.slice(0, mid)), bytes(full.slice(mid))])
    );
    vi.stubGlobal("fetch", fetchMock);

    const events: EventEnvelope[] = [];
    const handle = streamSession("s1", { onEvent: (e) => events.push(e) });
    await flush();
    handle.close();

    expect(events).toHaveLength(1);
    expect(events[0].job_id).toBe("split");
  });

  it("ignores malformed JSON frames without throwing", async () => {
    const good = env("ok");
    const fetchMock = vi.fn().mockResolvedValue(
      streamResponse([
        bytes(`id: 1\r\ndata: {not json}\r\n\r\nid: 2\r\ndata: ${good}\r\n\r\n`),
      ])
    );
    vi.stubGlobal("fetch", fetchMock);

    const events: EventEnvelope[] = [];
    const handle = streamSession("s1", { onEvent: (e) => events.push(e) });
    await flush();
    handle.close();

    expect(events.map((e) => e.job_id)).toEqual(["ok"]);
  });

  it("sends Last-Event-ID on reconnect equal to the last id seen", async () => {
    const first = liveResponse();
    const second = liveResponse();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(first.res)
      .mockResolvedValueOnce(second.res);
    vi.stubGlobal("fetch", fetchMock);

    const events: EventEnvelope[] = [];
    const handle = streamSession("s1", { onEvent: (e) => events.push(e) });
    await flush();

    // Stream an event carrying id "42", then end the stream to drive a retry.
    first.feed(`id: 42\r\ndata: ${env("j42")}\r\n\r\n`);
    await flush();
    expect(events.map((e) => e.job_id)).toEqual(["j42"]);

    // Force an immediate reconnect (skips backoff). The abort is a no-op on the
    // mock body, so end the stream to unblock read() and let the loop retry.
    handle.reconnect();
    first.endStream();
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const firstInit = fetchMock.mock.calls[0][1] as RequestInit;
    const secondInit = fetchMock.mock.calls[1][1] as RequestInit;
    expect((firstInit.headers as Record<string, string>)["Last-Event-ID"]).toBeUndefined();
    expect((secondInit.headers as Record<string, string>)["Last-Event-ID"]).toBe("42");

    handle.close();
  });

  it("sends a fresh Authorization header per (re)connect via getToken", async () => {
    const first = liveResponse();
    const second = liveResponse();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(first.res)
      .mockResolvedValueOnce(second.res);
    vi.stubGlobal("fetch", fetchMock);

    const tokens = ["tok-1", "tok-2"];
    const getToken = vi.fn(async () => tokens.shift());
    const handle = streamSession("s1", { getToken, onEvent: () => {} });
    await flush();

    handle.reconnect();
    first.endStream();
    await flush();

    const h0 = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    const h1 = fetchMock.mock.calls[1][1].headers as Record<string, string>;
    expect(h0.Authorization).toBe("Bearer tok-1");
    expect(h1.Authorization).toBe("Bearer tok-2");

    handle.close();
  });

  it("emits auth-error and onAuthError when the stream returns 401", async () => {
    const fetchMock = vi.fn().mockResolvedValue(streamResponse([], 401));
    vi.stubGlobal("fetch", fetchMock);

    const onAuthError = vi.fn();
    const handle = streamSession("s1", { onEvent: () => {}, onAuthError });
    await flush();
    handle.close();

    expect(onAuthError).toHaveBeenCalledWith(401);
  });

  it("close() stops the loop so no further fetch happens", async () => {
    const live = liveResponse();
    const fetchMock = vi.fn().mockResolvedValue(live.res);
    vi.stubGlobal("fetch", fetchMock);

    const handle = streamSession("s1", { onEvent: () => {} });
    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);

    handle.close();
    // End the underlying stream; a non-closed loop would reconnect — closed must not.
    live.endStream();
    await flush();
    await flush();

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("reports connection phases through onPhase", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      streamResponse([bytes(`id: 1\r\ndata: ${env("p")}\r\n\r\n`)])
    );
    vi.stubGlobal("fetch", fetchMock);

    const phases: string[] = [];
    const handle = streamSession("s1", {
      onEvent: () => {},
      onPhase: (p) => phases.push(p),
    });
    await flush();
    handle.close();

    expect(phases[0]).toBe("connecting");
    expect(phases).toContain("streaming");
  });
});

describe("artifactUrl", () => {
  it("returns http/https URLs unchanged", () => {
    expect(artifactUrl("http://x/y.png")).toBe("http://x/y.png");
    expect(artifactUrl("https://x/y.png")).toBe("https://x/y.png");
  });

  it("maps gs:// to the public storage host", () => {
    expect(artifactUrl("gs://my-bucket/path/to/file.txt")).toBe(
      "https://storage.googleapis.com/my-bucket/path/to/file.txt"
    );
  });

  it("prefixes relative paths with API_BASE", () => {
    expect(artifactUrl("/artifacts/1.png")).toBe(
      `${API_BASE}/artifacts/1.png`
    );
  });
});

describe("ApiError", () => {
  it("carries the HTTP status and message", () => {
    const err = new ApiError(404, "GET /x → 404");
    expect(err).toBeInstanceOf(Error);
    expect(err.name).toBe("ApiError");
    expect(err.status).toBe(404);
    expect(err.message).toBe("GET /x → 404");
  });
});
