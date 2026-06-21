#!/usr/bin/env python3
"""UserPromptSubmit hook: push the user's prompt to the runner transcript. exit 0."""

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

    push(
        "/internal/transcript",
        {
            "session_id": os.environ.get("ALPHA_SESSION_ID", ""),
            "job_id": os.environ.get("ALPHA_JOB_ID", ""),
            "role": "user",
            "content": str(data.get("prompt", ""))[:8000],
        },
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
