# Token-Level Streaming from the Main Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stream the main research agent's assistant narration into the live UI as a typewriter effect, in both the real `claude -p` cloud path and the local sim.

**Architecture:** A new additive `token` event rides the existing Redis-Stream event bus carrying `{msg_id, role, delta, final}`. The real agent's launcher spawns `claude` with `--output-format stream-json --include-partial-messages` and a pure relay module translates `text_delta` chunks into `token` events. The local sim chunks its canned assistant text into the same events. The frontend reducer coalesces deltas by `msg_id` into one growing transcript item — idempotent under SSE replay-from-0 and reconnect-resume because deltas are append-only and keyed by a stable id.

**Tech Stack:** Python 3.12 (pydantic, FastAPI, asyncio), stdlib-only agent launcher/hooks, pytest + fakeredis; Next.js/React + TypeScript, vitest + Testing Library.

## Global Constraints

- **Wire string is exactly `"token"`** — the literal the SSE consumer matches on.
- **`SCHEMA_VERSION` stays `2`** — adding an `EventType` member is additive/non-breaking.
- **Agent launcher, relay, and hooks are stdlib-only.** The agent container image excludes `infra/`, `runner/`, `orchestrator/` — never import from them in `agent/main-agent/`.
- **Files stay < 800 lines; single responsibility** (CLAUDE.md). The stream-json→event translation lives in its own module, not inlined into `launch.py`.
- **Token events carry `job_id = ALPHA_JOB_ID` (the main agent's root job), `depth = 0`** — matching how the sim emits today.
- **Only `text_delta` streams.** `thinking_delta`/`signature_delta` (extended thinking) and `input_json_delta` (tool input) are ignored; tool activity is reported by the existing `PostToolUse` hook.
- **Branch:** work on `feat/frontend-complete` (never `main`). Commit per task.
- Real `claude` stream-json shapes (verified against claude 2.1.183), used by the relay:
  - `{"type":"stream_event","event":{"type":"message_start","message":{"id":"msg_…",…}}}`
  - `{"type":"stream_event","event":{"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"…"}}}`
  - `{"type":"stream_event","event":{"type":"content_block_stop","index":1}}`
  - (thinking blocks use `index:0`, `delta.type` `thinking_delta`/`signature_delta` — ignored.)

---

### Task 1: Add the `token` event type to the wire contract

**Files:**
- Modify: `infra/schemas.py` (the `EventType` enum, ~line 35)
- Modify: `web/lib/types.ts` (the `EventType` union ~line 2; `TranscriptItem` ~line 190)
- Test: `tests/test_token_event.py` (create)

**Interfaces:**
- Produces: `EventType.token` (Python, value `"token"`); TS `EventType` includes `"token"`; `TranscriptItem` gains optional `msgId?: string` and `streaming?: boolean`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_token_event.py`:

```python
"""Token event contract — the wire member the typewriter UI matches on.

Pure unit tests of EventType.token and the EventEnvelope that carries a
streaming text delta. No Redis — mirrors tests/test_error_event.py.
"""

from __future__ import annotations

from infra.schemas import EventEnvelope, EventType


def test_token_member_exists_and_value():
    assert EventType.token == "token"
    assert EventType.token.value == "token"
    assert EventType("token") is EventType.token


def test_token_envelope_round_trips_through_json():
    env = EventEnvelope(
        session_id="s_1",
        job_id="j_1",
        type=EventType.token,
        payload={"msg_id": "msg_1#0", "role": "assistant", "delta": "hel", "final": False},
    )
    again = EventEnvelope.model_validate_json(env.model_dump_json())
    assert again.type is EventType.token
    assert again.payload == {
        "msg_id": "msg_1#0",
        "role": "assistant",
        "delta": "hel",
        "final": False,
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_token_event.py -v`
Expected: FAIL — `AttributeError: token` (member not yet defined).

- [ ] **Step 3: Add the enum member**

In `infra/schemas.py`, add `token` to `EventType` (keep alphabetical-ish ordering with the rest):

```python
class EventType(StrEnum):
    log = "log"
    metric = "metric"
    status = "status"
    spawn = "spawn"
    artifact = "artifact"
    summary = "summary"
    error = "error"
    token = "token"  # streaming assistant text delta (typewriter UI)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_token_event.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Update the TypeScript wire types**

In `web/lib/types.ts`, extend the `EventType` union:

```typescript
export type EventType =
  | "log"
  | "metric"
  | "status"
  | "spawn"
  | "artifact"
  | "summary"
  | "error"
  | "token";
```

And add two optional fields to `TranscriptItem`:

```typescript
export interface TranscriptItem {
  id: string;
  role: "user" | "assistant" | "tool" | "system";
  text: string;
  toolName?: string;
  /** Stable id shared by all token deltas of one streamed message block. */
  msgId?: string;
  /** True while deltas are still arriving (drives the typewriter caret). */
  streaming?: boolean;
}
```

- [ ] **Step 6: Verify the web types compile**

Run: `cd web && npx tsc --noEmit`
Expected: no new errors (exit 0).

- [ ] **Step 7: Commit**

```bash
git add infra/schemas.py web/lib/types.ts tests/test_token_event.py
git commit -m "feat(schema): add token event type for streaming assistant text"
```

---

### Task 2: `stream_relay.py` — translate stream-json into token events

**Files:**
- Create: `agent/main-agent/stream_relay.py`
- Test: `tests/test_stream_relay.py` (create)

**Interfaces:**
- Produces: `relay(lines: Iterable[str], emit: Callable[[str, dict], None], *, session_id: str, job_id: str, depth: int = 0) -> None`. For each `text_delta` it calls `emit("/internal/events", {…, "type": "token", "payload": {"msg_id": f"{message_id}#{index}", "role": "assistant", "delta": chunk, "final": False}})`; on `content_block_stop` of a text block it emits a final token (`delta:""`, `final:True`) and `emit("/internal/transcript", {"session_id", "job_id", "role":"assistant", "content": full_block_text})`.
- Consumes (in Task 3): the `emit` signature matches `_push.push(path, body)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_stream_relay.py`:

```python
"""stream_relay translates `claude --output-format stream-json
--include-partial-messages` stdout into token events + transcript messages.

Pure: feed canned (real-shaped) stream-json lines and a fake emit; assert the
event sequence. No network, no claude binary.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent" / "main-agent"))
from stream_relay import relay  # noqa: E402


def _lines(*events: dict) -> list[str]:
    """Wrap raw Anthropic stream events as claude stream_event envelope lines."""
    return [json.dumps({"type": "stream_event", "event": e}) for e in events]


def _run(lines):
    calls: list[tuple[str, dict]] = []
    relay(lines, lambda path, body: calls.append((path, body)),
          session_id="s1", job_id="j1", depth=0)
    return calls


def test_text_deltas_stream_then_finalize_and_persist():
    lines = _lines(
        {"type": "message_start", "message": {"id": "msg_A", "content": []}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": " world"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_stop"},
    )
    calls = _run(lines)

    events = [b for p, b in calls if p == "/internal/events"]
    transcripts = [b for p, b in calls if p == "/internal/transcript"]

    # Two streaming deltas + one final marker.
    assert [e["payload"]["delta"] for e in events] == ["Hello", " world", ""]
    assert [e["payload"]["final"] for e in events] == [False, False, True]
    # Stable, block-scoped msg_id; role + type are correct; routed to the bus.
    assert all(e["payload"]["msg_id"] == "msg_A#0" for e in events)
    assert all(e["type"] == "token" and e["payload"]["role"] == "assistant" for e in events)
    assert all(e["session_id"] == "s1" and e["job_id"] == "j1" for e in events)
    # The finished block is persisted once as a transcript message.
    assert len(transcripts) == 1
    assert transcripts[0] == {
        "session_id": "s1", "job_id": "j1", "role": "assistant", "content": "Hello world",
    }


def test_thinking_and_tool_deltas_are_ignored():
    lines = _lines(
        {"type": "message_start", "message": {"id": "msg_B", "content": []}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hmm"}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "abc"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "name": "Bash"}},
        {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{}"}},
        {"type": "content_block_stop", "index": 1},
        {"type": "message_stop"},
    )
    calls = _run(lines)
    # No text → no token events and no transcript persistence at all.
    assert calls == []


def test_multiple_messages_get_distinct_msg_ids():
    lines = _lines(
        {"type": "message_start", "message": {"id": "msg_A", "content": []}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "one"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_start", "message": {"id": "msg_C", "content": []}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "two"}},
        {"type": "content_block_stop", "index": 0},
    )
    events = [b for p, b in _run(lines) if p == "/internal/events"]
    msg_ids = {e["payload"]["msg_id"] for e in events}
    assert msg_ids == {"msg_A#0", "msg_C#0"}


def test_blank_and_non_json_lines_are_skipped():
    lines = ["", "   ", "not json", json.dumps({"type": "system", "subtype": "init"})]
    assert _run(lines) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_stream_relay.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'stream_relay'`.

- [ ] **Step 3: Write the relay module**

Create `agent/main-agent/stream_relay.py`:

```python
#!/usr/bin/env python3
"""Translate `claude -p --output-format stream-json --include-partial-messages`
stdout into runner telemetry: assistant TEXT streams as `token` deltas, and each
finished text block is persisted once as a transcript Message.

Pure + stdlib-only: ``relay()`` takes an injected ``emit(path, body)`` so it
unit-tests without a network or the claude binary. The agent image excludes
``infra/`` — do NOT import from it here.

Only ``text_delta``s are streamed. ``thinking_delta``/``signature_delta``
(extended thinking) and ``input_json_delta`` (tool input) are intentionally
ignored — tool activity is reported separately by the PostToolUse hook.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable

Emit = Callable[[str, dict], None]


def relay(
    lines: Iterable[str],
    emit: Emit,
    *,
    session_id: str,
    job_id: str,
    depth: int = 0,
) -> None:
    msg_id = ""               # current assistant message id (from message_start)
    text: dict[int, str] = {} # content-block index -> accumulated text so far

    def _token(block: int, delta: str, final: bool) -> None:
        emit(
            "/internal/events",
            {
                "session_id": session_id,
                "job_id": job_id,
                "depth": depth,
                "type": "token",
                "payload": {
                    "msg_id": f"{msg_id}#{block}",
                    "role": "assistant",
                    "delta": delta,
                    "final": final,
                },
            },
        )

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if obj.get("type") != "stream_event":
            continue
        ev = obj.get("event") or {}
        et = ev.get("type")

        if et == "message_start":
            msg_id = ((ev.get("message") or {}).get("id")) or msg_id
            text.clear()
        elif et == "content_block_delta":
            delta = ev.get("delta") or {}
            if delta.get("type") == "text_delta":
                idx = int(ev.get("index", 0))
                chunk = delta.get("text") or ""
                if chunk:
                    text[idx] = text.get(idx, "") + chunk
                    _token(idx, chunk, final=False)
        elif et == "content_block_stop":
            idx = int(ev.get("index", 0))
            full = text.pop(idx, "")
            if full:
                _token(idx, "", final=True)
                emit(
                    "/internal/transcript",
                    {
                        "session_id": session_id,
                        "job_id": job_id,
                        "role": "assistant",
                        "content": full,
                    },
                )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_stream_relay.py -v`
Expected: PASS (all four tests).

- [ ] **Step 5: Commit**

```bash
git add agent/main-agent/stream_relay.py tests/test_stream_relay.py
git commit -m "feat(agent): stream-json -> token event relay (assistant text)"
```

---

### Task 3: Rewrite `launch.py` to spawn claude with stream-json and drive the relay

**Files:**
- Modify: `agent/main-agent/launch.py` (replace the `os.execvp` tail of `main()`, ~lines 54-69; add imports)
- Test: `tests/test_launch_argv.py` (create)

**Interfaces:**
- Consumes: `stream_relay.relay`, `_push.push` (the hooks' HTTP helper).
- Produces: `_build_argv(prompt: str, model: str) -> list[str]` returning the claude invocation including the stream-json flags.

- [ ] **Step 1: Write the failing test**

Create `tests/test_launch_argv.py`:

```python
"""launch._build_argv must invoke claude in streaming print mode so the relay
can tail assistant text. Pure argv assertion — no subprocess, no claude binary.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent" / "main-agent"))
import launch  # noqa: E402


def test_build_argv_uses_streaming_print_mode():
    argv = launch._build_argv("do the thing", "claude-sonnet-4-6")
    assert argv[0] == "claude"
    # Print mode with the prompt, the model, and streaming JSON deltas.
    assert "-p" in argv and "do the thing" in argv
    assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv            # required with -p + stream-json
    assert "--include-partial-messages" in argv  # token-level deltas
    assert "--dangerously-skip-permissions" in argv
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_launch_argv.py -v`
Expected: FAIL — `AttributeError: module 'launch' has no attribute '_build_argv'`.

- [ ] **Step 3: Rewrite the launcher**

In `agent/main-agent/launch.py`, replace the imports block and `main()`. Keep `_bootstrap` and `_prompt` unchanged. New top-of-file imports (add `subprocess`; drop nothing that `_bootstrap` uses):

```python
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_HOOKS = str(Path(__file__).resolve().parent / ".claude" / "hooks")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, _HOOKS)
from _push import push  # noqa: E402  (stdlib-only HTTP helper, shared with hooks)
from stream_relay import relay  # noqa: E402
```

Add `_build_argv` above `main()`:

```python
def _build_argv(prompt: str, model: str) -> list[str]:
    """claude in streaming print mode: emit per-token JSON so the relay can
    forward assistant text live. --verbose is required with -p + stream-json."""
    return [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--dangerously-skip-permissions",
    ]
```

Replace the tail of `main()` (everything from `os.environ["ALPHA_NONINTERACTIVE"] = "1"` onward) with:

```python
    os.environ["ALPHA_NONINTERACTIVE"] = "1"  # CLAUDE.md gates its clarifying-Q step on this

    session_id = os.environ.get("ALPHA_SESSION_ID", "")
    job_id = os.environ.get("ALPHA_JOB_ID", "")
    try:
        depth = int(os.environ.get("ALPHA_DEPTH") or 0)
    except ValueError:
        depth = 0

    # Spawn claude (don't exec) so we can tail its stream-json stdout and relay
    # assistant text deltas to the runner. stderr inherits -> Cloud Run logs.
    argv = _build_argv(_prompt(goal), model)
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True, bufsize=1)
    try:
        relay(proc.stdout, push, session_id=session_id, job_id=job_id, depth=depth)
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        rc = proc.wait()
    sys.exit(rc)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_launch_argv.py -v`
Expected: PASS.

- [ ] **Step 5: Sanity-check the module imports cleanly**

Run: `uv run python -c "import sys; sys.path.insert(0,'agent/main-agent'); import launch; print('ok', bool(launch._build_argv))"`
Expected: prints `ok True` (no import error from the `_push`/`stream_relay` path wiring).

- [ ] **Step 6: Commit**

```bash
git add agent/main-agent/launch.py tests/test_launch_argv.py
git commit -m "feat(agent): launcher streams claude stdout through the token relay"
```

---

### Task 4: Fix the PostToolUse hook to emit a reducer-shaped tool log

**Files:**
- Modify: `agent/main-agent/.claude/hooks/stream_event.py`
- Test: `tests/test_stream_event_hook.py` (create)

**Interfaces:**
- Produces: `build_event(data: dict, *, session_id: str, job_id: str, depth: int) -> dict` returning a `log` event whose payload is `{"role": "tool_use", "tool_name": <tool>, "content": <short input preview>}` — the shape `web/lib/session-reducer.ts` maps to a `tool` transcript line.

**Why:** today the hook emits `{tool, input, result}`, which the reducer doesn't read (`p.role`/`p.content`/`p.tool_name` are all absent), so tool calls render as empty assistant lines. This makes the real-agent transcript coherent alongside streamed text.

- [ ] **Step 1: Write the failing test**

Create `tests/test_stream_event_hook.py`:

```python
"""The PostToolUse hook must emit a `log` event in the shape the web reducer
reads: role=tool_use + tool_name + a short content preview. Pure builder test.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent" / "main-agent" / ".claude" / "hooks"))
import stream_event  # noqa: E402


def test_build_event_is_a_tool_use_log():
    data = {"tool_name": "Bash", "tool_input": {"command": "ls -la"}, "tool_response": "a\nb"}
    body = stream_event.build_event(data, session_id="s1", job_id="j1", depth=0)
    assert body["type"] == "log"
    assert body["session_id"] == "s1" and body["job_id"] == "j1" and body["depth"] == 0
    p = body["payload"]
    assert p["role"] == "tool_use"
    assert p["tool_name"] == "Bash"
    assert "ls -la" in p["content"]  # short, human-readable input preview


def test_build_event_handles_missing_fields():
    body = stream_event.build_event({}, session_id="s1", job_id="j1", depth=0)
    p = body["payload"]
    assert p["role"] == "tool_use"
    assert p["tool_name"] == ""
    assert isinstance(p["content"], str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_stream_event_hook.py -v`
Expected: FAIL — `AttributeError: module 'stream_event' has no attribute 'build_event'`.

- [ ] **Step 3: Rewrite the hook**

Replace the body of `agent/main-agent/.claude/hooks/stream_event.py` with:

```python
#!/usr/bin/env python3
"""PostToolUse hook: stream a 'tool_use' log event to the runner so each tool
call shows as a line in the chat transcript. Emits the shape the web reducer
reads (role + tool_name + content). exit 0 always."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _push import push  # noqa: E402

_MAX_PREVIEW = 200


def _preview(tool: str, tool_input: dict) -> str:
    """A short, human-readable summary of the call (fallback transcript text)."""
    try:
        rendered = json.dumps(tool_input, ensure_ascii=False)
    except (TypeError, ValueError):
        rendered = str(tool_input)
    return f"{tool} {rendered}"[:_MAX_PREVIEW].strip()


def build_event(data: dict, *, session_id: str, job_id: str, depth: int) -> dict:
    tool = str(data.get("tool_name", ""))
    tool_input = data.get("tool_input") or {}
    return {
        "session_id": session_id,
        "job_id": job_id,
        "depth": depth,
        "type": "log",
        "payload": {
            "role": "tool_use",
            "tool_name": tool,
            "content": _preview(tool, tool_input),
        },
    }


def main() -> None:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        data = {}

    try:
        depth = int(os.environ.get("ALPHA_DEPTH") or 0)
    except ValueError:
        depth = 0

    push(
        "/internal/events",
        build_event(
            data,
            session_id=os.environ.get("ALPHA_SESSION_ID", ""),
            job_id=os.environ.get("ALPHA_JOB_ID", ""),
            depth=depth,
        ),
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_stream_event_hook.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add agent/main-agent/.claude/hooks/stream_event.py tests/test_stream_event_hook.py
git commit -m "fix(agent): PostToolUse hook emits reducer-shaped tool_use log"
```

---

### Task 5: Local sim — chunk assistant text into token events

**Files:**
- Modify: `runner/local_sim.py` (add `import re`; add `_TOKEN_TICK`, `_chunk_text`, `_stream_assistant`; route `_msg` assistant role through it — `_msg` is ~lines 46-51)
- Test: `tests/test_local_sim_tokens.py` (create)

**Interfaces:**
- Consumes: `EventType.token` (Task 1), `store.emit_event`, `store.append_message`, `store.new_id`.
- Produces: `_chunk_text(content: str, group: int = 3) -> list[str]` (deltas concatenate back to `content`); `_stream_assistant(sid, jid, content)` emits a token sequence (last `final=True`) then persists the Message. `_msg` with `role="assistant"` now streams.

- [ ] **Step 1: Write the failing test**

Create `tests/test_local_sim_tokens.py`:

```python
"""Local-sim assistant messages stream as token deltas (typewriter), and the
deltas reconstruct the original text exactly. Captures emit/append via
monkeypatch + a no-op sleep — no timing, no real Redis needed.
"""

from __future__ import annotations

import asyncio

import pytest

from infra import store
from infra.schemas import EventType
from runner import local_sim


def test_chunk_text_reconstructs_exactly():
    text = "Curiosity cracked the key-door chaining at 0.81 success."
    chunks = local_sim._chunk_text(text)
    assert len(chunks) > 1            # actually chunked, not one blob
    assert "".join(chunks) == text    # deltas concatenate back to the original


def test_chunk_text_empty_is_no_chunks():
    assert local_sim._chunk_text("") == []


@pytest.mark.asyncio
async def test_stream_assistant_emits_tokens_then_persists(monkeypatch):
    events = []
    messages = []

    async def fake_emit(ev):
        events.append(ev)

    async def fake_append(m):
        messages.append(m)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(store, "emit_event", fake_emit)
    monkeypatch.setattr(store, "append_message", fake_append)
    monkeypatch.setattr(local_sim.asyncio, "sleep", no_sleep)

    content = "X is the clear winner here."
    await local_sim._stream_assistant("s1", "root", content)

    assert events, "expected token events"
    assert all(e.type is EventType.token for e in events)
    # One stable msg_id across the whole message.
    assert len({e.payload["msg_id"] for e in events}) == 1
    # Deltas reconstruct the content; only the last is final.
    assert "".join(e.payload["delta"] for e in events) == content
    assert [e.payload["final"] for e in events][-1] is True
    assert all(f is False for f in [e.payload["final"] for e in events][:-1])
    # The full message is persisted once for the /full snapshot.
    assert len(messages) == 1
    assert messages[0].role == "assistant" and messages[0].content == content
```

Note: the suite already supports async tests (see `tests/test_api_full_session.py`). If `@pytest.mark.asyncio` is unavailable, run with `uv run pytest -p anyio` is not needed — the repo's pytest config registers asyncio mode; confirm in Step 2.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_local_sim_tokens.py -v`
Expected: FAIL — `AttributeError: module 'runner.local_sim' has no attribute '_chunk_text'`.

- [ ] **Step 3: Add chunking + streaming, route `_msg` through it**

In `runner/local_sim.py`, add `import re` near the top (after `import asyncio`). Add a constant beside `_TICK`:

```python
# Typewriter pacing for assistant narration. Short so a message types out in
# ~0.5-1s without dragging the ~10s scripted run.
_TOKEN_TICK = 0.04
```

Replace `_msg` with:

```python
async def _msg(sid, jid, role, content) -> None:
    # Assistant narration types out as `token` deltas (typewriter). User/tool/
    # system lines stay atomic `log` events.
    if role == "assistant":
        await _stream_assistant(sid, jid, content)
        return
    await store.append_message(
        Message(session_id=sid, job_id=jid, role=role, content=content)
    )
    await _emit(sid, jid, 0, EventType.log, {"role": role, "content": content})


def _chunk_text(content: str, group: int = 3) -> list[str]:
    """Split `content` into ~`group`-word chunks, preserving trailing whitespace
    so that ``"".join(chunks) == content`` (deltas concatenate back exactly)."""
    words = re.findall(r"\S+\s*", content)
    if not words:
        return []
    return ["".join(words[i : i + group]) for i in range(0, len(words), group)]


async def _stream_assistant(sid, jid, content) -> None:
    """Emit `content` as a sequence of token deltas (last one final), then persist
    the whole message for the /full snapshot. Mirrors what stream_relay does for
    the real agent."""
    msg_id = store.new_id("m")
    chunks = _chunk_text(content)
    last = len(chunks) - 1
    for i, chunk in enumerate(chunks):
        await _emit(
            sid, jid, 0, EventType.token,
            {"msg_id": msg_id, "role": "assistant", "delta": chunk, "final": i == last},
        )
        await asyncio.sleep(_TOKEN_TICK)
    await store.append_message(
        Message(session_id=sid, job_id=jid, role="assistant", content=content)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_local_sim_tokens.py -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add runner/local_sim.py tests/test_local_sim_tokens.py
git commit -m "feat(local-sim): stream assistant narration as token deltas"
```

---

### Task 6: Frontend reducer — coalesce token deltas into one transcript item

**Files:**
- Modify: `web/lib/session-reducer.ts` (add a `token` branch right after the `log` branch, ~line 91)
- Test: `web/lib/__tests__/session-reducer.test.ts` (append a describe block)

**Interfaces:**
- Consumes: `EventType` `"token"` and `TranscriptItem.msgId`/`streaming` (Task 1).
- Produces: a `token` event with a new `msg_id` appends a streaming assistant `TranscriptItem`; subsequent deltas with the same `msg_id` append to its `text`; `final:true` clears `streaming`.

- [ ] **Step 1: Write the failing test**

Append to `web/lib/__tests__/session-reducer.test.ts` (uses the existing `env`/`reduce` helpers):

```typescript
// ─── (h) token events coalesce into one streaming assistant item ─────────────

describe("token events → coalesced typewriter transcript item", () => {
  it("grows one assistant item by msg_id and clears streaming on final", () => {
    const events: EventEnvelope[] = [
      env({ type: "token", job_id: "root", payload: { msg_id: "m1#0", role: "assistant", delta: "Hel", final: false } }),
      env({ type: "token", job_id: "root", payload: { msg_id: "m1#0", role: "assistant", delta: "lo ", final: false } }),
      env({ type: "token", job_id: "root", payload: { msg_id: "m1#0", role: "assistant", delta: "world", final: true } }),
    ];
    const state = reduce(events);
    // One transcript item, not three; full text assembled; no phantom job.
    expect(state.transcript).toHaveLength(1);
    expect(state.transcript[0].role).toBe("assistant");
    expect(state.transcript[0].text).toBe("Hello world");
    expect(state.transcript[0].streaming).toBe(false);
    expect(state.transcript[0].msgId).toBe("m1#0");
    expect(state.order).toEqual([]); // token events never create jobs
  });

  it("keeps streaming true while deltas are mid-flight", () => {
    const state = reduce([
      env({ type: "token", job_id: "root", payload: { msg_id: "m2#0", role: "assistant", delta: "typing", final: false } }),
    ]);
    expect(state.transcript[0].streaming).toBe(true);
  });

  it("separates distinct msg_ids into distinct items", () => {
    const state = reduce([
      env({ type: "token", job_id: "root", payload: { msg_id: "m1#0", delta: "a", final: true } }),
      env({ type: "token", job_id: "root", payload: { msg_id: "m2#0", delta: "b", final: true } }),
    ]);
    expect(state.transcript.map((t) => t.text)).toEqual(["a", "b"]);
    expect(state.transcript.map((t) => t.id)).toEqual(["t0", "t1"]);
  });

  it("replaying the full token stream yields identical state (idempotent)", () => {
    const events: EventEnvelope[] = [
      env({ type: "token", job_id: "root", payload: { msg_id: "m1#0", delta: "one ", final: false } }),
      env({ type: "token", job_id: "root", payload: { msg_id: "m1#0", delta: "two", final: true } }),
    ];
    expect(reduce(events)).toEqual(reduce(events));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run lib/__tests__/session-reducer.test.ts`
Expected: FAIL — token events fall through to job logic; `transcript` is empty / `order` is `["root"]`.

- [ ] **Step 3: Add the token branch to the reducer**

In `web/lib/session-reducer.ts`, immediately after the `if (env.type === "log") { … }` block (before the `error` block), add:

```typescript
  // Streaming assistant text: coalesce token deltas into one growing item,
  // keyed by a stable msg_id. Append-only + keyed => idempotent under SSE
  // replay-from-0 and reconnect-resume. Handled here (before job logic) so a
  // token event never creates a phantom job.
  if (env.type === "token") {
    const msgId = String(p.msg_id ?? "");
    const delta = String(p.delta ?? "");
    const final = Boolean(p.final);
    const i = prev.transcript.findIndex((t) => t.msgId === msgId);
    if (i >= 0) {
      const transcript = prev.transcript.slice();
      transcript[i] = {
        ...transcript[i],
        text: transcript[i].text + delta,
        streaming: !final,
      };
      return { ...prev, transcript };
    }
    return appendTranscript(prev, {
      role: "assistant",
      text: delta,
      msgId,
      streaming: !final,
    });
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run lib/__tests__/session-reducer.test.ts`
Expected: PASS (all describe blocks, including the new `(h)`).

- [ ] **Step 5: Commit**

```bash
git add web/lib/session-reducer.ts web/lib/__tests__/session-reducer.test.ts
git commit -m "feat(web): reducer coalesces token deltas into a typewriter item"
```

---

### Task 7: Transcript UI — blinking typewriter caret

**Files:**
- Modify: `web/components/chat-transcript.tsx` (the assistant `<p>` branch, ~lines 121-125)
- Test: `web/components/__tests__/chat-transcript.test.tsx` (create)

**Interfaces:**
- Consumes: `TranscriptItem.streaming` (Task 1), folded by the reducer (Task 6).
- Produces: a caret element (`data-testid="stream-caret"`) rendered only on streaming assistant items.

- [ ] **Step 1: Write the failing test**

Create `web/components/__tests__/chat-transcript.test.tsx` (mirrors the render style of `states.test.tsx`):

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ChatTranscript } from "@/components/chat-transcript";
import type { TranscriptItem } from "@/lib/types";

function item(over: Partial<TranscriptItem>): TranscriptItem {
  return { id: "t0", role: "assistant", text: "hello", ...over };
}

describe("ChatTranscript typewriter caret", () => {
  it("shows a caret on a streaming assistant item", () => {
    render(<ChatTranscript items={[item({ streaming: true })]} />);
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByTestId("stream-caret")).toBeInTheDocument();
  });

  it("shows no caret once streaming has finished", () => {
    render(<ChatTranscript items={[item({ streaming: false })]} />);
    expect(screen.queryByTestId("stream-caret")).toBeNull();
  });

  it("shows no caret on a user message", () => {
    render(<ChatTranscript items={[item({ role: "user", streaming: true })]} />);
    expect(screen.queryByTestId("stream-caret")).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run components/__tests__/chat-transcript.test.tsx`
Expected: FAIL — `Unable to find element by: [data-testid="stream-caret"]`.

- [ ] **Step 3: Render the caret**

In `web/components/chat-transcript.tsx`, replace the assistant paragraph branch (the `else` of the `m.role === "user"` ternary) so the caret renders inside it when streaming:

```tsx
                ) : (
                  <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-body">
                    {m.text}
                    {m.streaming && (
                      <span
                        data-testid="stream-caret"
                        aria-hidden
                        className="ml-px inline-block animate-pulse text-sunset"
                      >
                        ▍
                      </span>
                    )}
                  </p>
                )}
```

(The `user` branch and the `tool`/`system` early returns are unchanged — `streaming` only ever rides on assistant items.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run components/__tests__/chat-transcript.test.tsx`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add web/components/chat-transcript.tsx web/components/__tests__/chat-transcript.test.tsx
git commit -m "feat(web): blinking typewriter caret on streaming assistant turns"
```

---

### Task 8: Full verification — suites green + live typewriter demo

**Files:** none (verification only).

- [ ] **Step 1: Python suite**

Run: `uv run pytest -q`
Expected: all tests pass (including the four new files). If a pre-existing unrelated test fails, note it but do not let the new tests regress.

- [ ] **Step 2: Web unit tests + lint + types**

Run:
```bash
cd web && npx vitest run && npx tsc --noEmit && npx eslint .
```
Expected: vitest all-green (reducer + chat-transcript additions), no TS errors, no lint errors.

- [ ] **Step 3: Live local-sim demo (manual, requires Redis)**

With a Redis reachable per `.env` (`REDIS_URL`/Redis Cloud), run the API in local-sim mode and the web app, then watch the lead-agent turns type out:

```bash
# terminal 1 — API in local-sim mode
ALPHA_LOCAL_SIM=true uv run uvicorn orchestrator.api:app --port 8080
# terminal 2 — web
cd web && npm run dev
```
Open the web app, create a session, and confirm: the "Lead agent" turns appear character-grouped with a blinking caret that clears when each turn finishes; tool lines (`used Bash`) still render; reward charts/tree/artifacts still populate.

- [ ] **Step 4: Optional — confirm `token` frames on the raw SSE stream**

```bash
curl -N http://localhost:8080/sessions/<sid>/stream | grep -m1 '"type": "token"'
```
Expected: at least one `token` event frame is observed during a run.

- [ ] **Step 5: Final commit (if any verification fixups were needed)**

```bash
git add -A && git commit -m "test: verify token streaming end-to-end"
```

---

## Self-Review

**Spec coverage:**
- New `token` event type (spec §"Wire protocol") → Task 1. ✓
- Real agent stream-json relay + launcher rewrite (spec §1) → Tasks 2-3. ✓
- Adjacent `stream_event.py` tool-log bugfix (spec §1) → Task 4. ✓
- Local-sim chunked streaming (spec §2) → Task 5. ✓
- Reducer coalescing + `TranscriptItem` fields (spec §3) → Tasks 1 & 6. ✓
- Transcript caret (spec §3) → Task 7. ✓
- Tests: relay fixture, local-sim emission, reducer idempotency (spec §4) → Tasks 2, 5, 6 (+ schema Task 1, hook Task 4, UI Task 7). ✓
- Idempotency-under-replay invariant (spec §"Key invariant") → exercised by Task 6 Step 1's replay test. ✓
- Out-of-scope (thinking stream; no backend route changes) → respected: relay ignores `thinking_delta`; no store/API route added. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every code step shows complete code; every run step shows the command and expected result. ✓

**Type consistency:** `relay(lines, emit, *, session_id, job_id, depth)` and the `emit(path, body)` shape match between Task 2 (def + test) and Task 3 (call with `push`). `build_event(data, *, session_id, job_id, depth)` matches between Task 4's def and test. `_chunk_text`/`_stream_assistant` names match between Task 5's def and test. Payload keys `msg_id`/`role`/`delta`/`final` are identical across relay (Task 2), sim (Task 5), reducer (Task 6), and tests. `TranscriptItem.msgId`/`streaming` defined in Task 1 and consumed in Tasks 6-7. ✓
