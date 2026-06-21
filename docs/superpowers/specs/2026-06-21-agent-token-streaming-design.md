# Token-level streaming from the main agent — design

**Date:** 2026-06-21
**Status:** approved (design); pending spec review
**Branch:** `feat/frontend-complete`

## Problem

The main research agent's reasoning is invisible in the live UI.

- The **real** main agent runs headless as `claude -p` on a Cloud Run Job
  ([`agent/main-agent/launch.py`](../../../agent/main-agent/launch.py)). It
  `os.execvp`s `claude`, so the agent's assistant narration goes to discarded
  stdout. The only telemetry is a per-tool `log` event (`stream_event.py`) and a
  `{finished: true}` summary on `Stop` (`finalize.py`). Its actual thinking never
  reaches the bus.
- The **local sim** (`runner/local_sim.py`) fakes narration: `_msg(...,
  "assistant", ...)` mirrors a complete `log` event onto the bus. But it arrives
  as one block — no typewriter feel.

We want the main agent's text to **type out live** in the transcript, in both the
real cloud path and the local sim (so it is demoable in dev today, where no cloud
backend is deployed/verified).

## Key invariant that makes this safe

The transcript is rebuilt **entirely by folding the event stream** — the frontend
hook (`web/hooks/use-session.ts`) ignores `/full`'s stored transcript and replays
events:

- First connect: `Last-Event-ID` absent → server streams from `0` (full replay).
- Reconnect: `streamSession` keeps `lastId`, sends `Last-Event-ID`, server resumes
  **after** it, and the reducer state is **not** reset.

Therefore **append-only deltas keyed by a stable message id are idempotent** under
both first-connect replay and reconnect-resume. This is the foundation of the whole
design — token deltas can be replayed or resumed without duplication.

## Wire protocol — new `token` event type

Add `token` to `EventType` in [`infra/schemas.py`](../../../infra/schemas.py) and to
the TS `EventType` union in `web/lib/types.ts`. Payload shape:

```jsonc
{
  "msg_id": "string",   // stable across all deltas of one text block
  "role": "assistant",
  "delta": "string",    // the incremental text chunk
  "final": false         // true on the last delta of the block
}
```

Decisions:

- A new event type (not overloaded `log`) keeps `log` meaning "atomic message"
  (user / tool / system / non-streamed assistant). Streamed text has exactly **one**
  path → no log/token dedup logic.
- Token events carry `job_id = root job id`, `depth = 0` (the main agent's node),
  matching how the sim emits `_msg` today.
- `msg_id`: real agent uses `"{message.id}#{content_block_index}"` from stream-json;
  sim uses `store.new_id("m")` per assistant message. Determinism across replays is
  not required — the id is baked into the stored event, so replay is byte-identical.
- Additive change: `SCHEMA_VERSION` stays `2`. Old clients ignore unknown `token`
  events (the reducer handles them in an early branch; see below).
- Tool calls and user/system lines stay **atomic `log` events** — they do not "type".

## Component changes

### 1. Real agent — `agent/main-agent/launch.py` + new `stream_relay.py`

Replace `os.execvp` with a subprocess that streams:

```
claude -p <prompt> --output-format stream-json --verbose --include-partial-messages
```

Read stdout line-by-line and translate each JSON message in a **new focused module**
`agent/main-agent/stream_relay.py` (keeps `launch.py` small and the translation
unit-testable; both stay stdlib-only, mirroring `_push.py`):

- `stream_event` → inner `content_block_delta` with `text_delta` → POST a `token`
  event (`delta` = the chunk, `msg_id` = `"{message.id}#{block_index}"`).
- `content_block_stop` for a text block → POST a final `token` (`final: true`) **and**
  POST the full block text to `/internal/transcript` (durable `Message` for `/full`).
- Forward `claude`'s exit code; the `Stop` hook still fires `finalize.py`.

Flags to verify at implementation time (`claude --help`): `--output-format
stream-json`, `--verbose` (required with `-p` + stream-json), `--include-partial-messages`.

**Adjacent bugfix (in scope):** `agent/main-agent/.claude/hooks/stream_event.py`
currently emits `{tool, input, result}`, which the reducer does not read, so tool
lines render empty. Change it to emit a `log` event with `{role: "tool_use",
content: "<tool + brief input>", tool_name: "<tool>"}` so tool activity shows. Tool
telemetry stays owned by the `PostToolUse` hook; the launcher owns assistant text.

### 2. Local sim — `runner/local_sim.py`

`_msg(role="assistant", ...)` chunks `content` into ~word-group deltas, emits a
sequence of `token` events sharing a fresh `msg_id` with small `asyncio.sleep`
pauses (visible typewriter), the last with `final: true`, then persists the
`Message`. `user` / tool / system messages stay atomic `log` events.
`respond_to_message` inherits streaming for free (it calls `_msg`).

### 3. Frontend — reducer + transcript UI

`web/lib/session-reducer.ts`:

- Handle `token` in the **early branch** (alongside `log`/`error`, before the
  job-upsert logic) so it never creates phantom jobs.
- Find the transcript item by `msgId`. First delta → create an `assistant` item with
  `streaming: true`; subsequent deltas → append to its `text`; `final` → clear
  `streaming`. Item id is assigned once from `seq` at creation (deltas match by
  `msgId`, not index), so full replay rebuilds identical ids.
- `TranscriptItem` gains `msgId?: string` and `streaming?: boolean` in
  `web/lib/types.ts`.

`web/components/chat-transcript.tsx`: render a blinking caret after a `streaming`
assistant item's text.

### 4. Tests

- **Python:** `stream_relay` fixture test — feed canned stream-json lines, assert the
  exact sequence of posted events (`token` deltas → `final` → transcript Message).
  Local-sim token-emission test (mirrors `tests/test_error_event.py` style).
- **TS (vitest, already configured):** reducer test — a delta sequence coalesces into
  one growing assistant item; replaying the same events from scratch yields identical
  state (idempotency).

## Out of scope (YAGNI)

- Streaming extended-**thinking** blocks as a separate dimmed role (stream-json
  exposes `thinking` deltas; deferred unless requested).
- Any backend change beyond the new `EventType` value (no store/API route changes —
  `/internal/events` and `/internal/transcript` already exist).

## Risks / notes

- `claude` stream-json flag names must be confirmed against the installed CLI before
  coding the relay.
- The launcher now manages a child process instead of `exec`; it must forward the
  exit code and not hang if `claude` closes stdout early.
- Token events increase event volume on the bus; the reducer already caps transcript
  length (`MAX_TRANSCRIPT`), and deltas coalesce into one item, so memory stays bounded.
