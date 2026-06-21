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
            # Real claude streams always carry message.id; reset (don't inherit the
            # prior message's id) so a malformed start can't merge two messages.
            msg_id = ((ev.get("message") or {}).get("id")) or ""
            text.clear()
        elif et == "content_block_delta":
            delta = ev.get("delta") or {}
            if delta.get("type") == "text_delta":
                idx = int(ev.get("index", 0))
                chunk = delta.get("text") or ""
                if chunk:  # skip empty deltas — nothing to stream or accumulate
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
