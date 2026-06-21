#!/usr/bin/env python3
"""Stop hook (sub agent): atomically write RunResult to the shared volume,
then push a summary event. SEV-7 atomic write. Never fails the agent.

The sub-agent's volume is mounted at ``$ALPHA_DISPATCH_DIR`` (default
``/workspace/.dispatched``). We write ``<jid>.result.json`` via a tmp file +
atomic ``os.replace``, then touch ``<jid>.result.json.done`` as a sentinel so
the runner only ever reads a fully-written result (no torn JSON on crash).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _push import push  # noqa: E402


def main() -> None:
    summary = ""
    jid = os.environ.get("ALPHA_JOB_ID", "")
    try:
        ws = Path(os.environ.get("ALPHA_WORKSPACE", "/workspace"))
        dispatch = Path(os.environ.get("ALPHA_DISPATCH_DIR", "/workspace/.dispatched"))

        summary_path = ws / "result_summary.txt"
        summary = summary_path.read_text() if summary_path.exists() else ""

        metrics: dict = {}
        metrics_path = ws / "result_metrics.json"
        if metrics_path.exists():
            try:
                metrics = json.loads(metrics_path.read_text())
            except (json.JSONDecodeError, ValueError):
                metrics = {"_parse_error": True}

        result = {
            "job_id": jid,
            "status": "done",
            "summary": summary.strip()[:4000],
            "metrics": metrics,
        }

        dispatch.mkdir(parents=True, exist_ok=True)
        tmp = dispatch / (jid + ".result.json.tmp")
        final = dispatch / (jid + ".result.json")
        tmp.write_text(json.dumps(result))
        os.replace(tmp, final)  # atomic rename — no torn reads
        (dispatch / (jid + ".result.json.done")).write_text(datetime.now(UTC).isoformat())
    except Exception as err:  # noqa: BLE001 — telemetry hook must never fail the agent
        print(f"[finalize] {err}", file=sys.stderr)

    try:
        depth = int(os.environ.get("ALPHA_DEPTH") or "1")
    except ValueError:
        depth = 1

    push(
        "/internal/events",
        {
            "session_id": os.environ.get("ALPHA_SESSION_ID", ""),
            "job_id": jid,
            "depth": depth,
            "type": "summary",
            "payload": {"finished": True, "summary": summary[:240]},
        },
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
