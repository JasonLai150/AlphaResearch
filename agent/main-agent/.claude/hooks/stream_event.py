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
    # tool_response is intentionally omitted — this event represents the tool
    # INVOCATION (the transcript "used <tool>" line), not the result.
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
