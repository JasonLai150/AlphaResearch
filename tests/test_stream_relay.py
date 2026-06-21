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


def test_empty_text_delta_is_skipped():
    lines = _lines(
        {"type": "message_start", "message": {"id": "msg_E", "content": []}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "hi"}},
        {"type": "content_block_stop", "index": 0},
    )
    events = [b for p, b in _run(lines) if p == "/internal/events"]
    # The empty delta is dropped; only the real chunk + the final marker remain.
    assert [e["payload"]["delta"] for e in events] == ["hi", ""]
    transcripts = [b for p, b in _run(lines) if p == "/internal/transcript"]
    assert transcripts[0]["content"] == "hi"
