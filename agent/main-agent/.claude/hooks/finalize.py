#!/usr/bin/env python3
"""Stop hook (main agent): push a 'finished' summary. No structured result. exit 0."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _push import push  # noqa: E402


def main() -> None:
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
            "type": "summary",
            "payload": {"finished": True},
        },
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
