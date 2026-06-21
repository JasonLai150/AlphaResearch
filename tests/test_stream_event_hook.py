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


def test_build_event_truncates_long_input():
    big = {"x": "a" * 300}
    body = stream_event.build_event(
        {"tool_name": "T", "tool_input": big}, session_id="s", job_id="j", depth=0
    )
    assert len(body["payload"]["content"]) <= 200
