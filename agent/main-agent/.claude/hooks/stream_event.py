#!/usr/bin/env python3
"""PostToolUse hook: stream a per-tool 'log' event to the runner. exit 0 always."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _push import push  # noqa: E402


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
        {
            "session_id": os.environ.get("ALPHA_SESSION_ID", ""),
            "job_id": os.environ.get("ALPHA_JOB_ID", ""),
            "depth": depth,
            "type": "log",
            "payload": {
                "tool": data.get("tool_name", ""),
                "input": data.get("tool_input", {}),
                "result": str(data.get("tool_response", ""))[:1000],
            },
        },
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
