#!/usr/bin/env python3
"""Stop hook (sub agent): publish the agent's RunResult into the shared volume,
then push a summary event. SEV-7 atomic write. Never fails the agent.

The agent is instructed (CLAUDE.md) to write its full RunResult to
``$ALPHA_WORKSPACE/result.json``. This hook copies that into the per-session
volume at ``$ALPHA_DISPATCH_DIR/<jid>.result.json`` via a tmp file + atomic
``os.replace``, then touches ``<jid>.result.json.done`` as a sentinel so the
runner only ever reads a fully-written result (no torn JSON on crash). If the
agent produced no/invalid result.json, we publish a ``failed`` result so the
runner finalizes the job instead of polling it forever.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _push import push  # noqa: E402


def _load_result(ws: Path, jid: str) -> dict:
    rp = ws / "result.json"
    if not rp.exists():
        return {"job_id": jid, "status": "failed", "summary": "sub-agent produced no result.json",
                "metrics": {}}
    try:
        data = json.loads(rp.read_text())
    except (json.JSONDecodeError, ValueError, OSError):
        return {"job_id": jid, "status": "failed",
                "summary": "result.json present but invalid JSON", "metrics": {}}
    if not isinstance(data, dict):
        return {"job_id": jid, "status": "failed", "summary": "result.json not an object",
                "metrics": {}}
    data.setdefault("job_id", jid)
    data.setdefault("status", "done")
    data.setdefault("metrics", {})
    return data


def main() -> None:
    jid = os.environ.get("ALPHA_JOB_ID", "")
    result: dict = {"job_id": jid, "status": "failed", "summary": "finalize error", "metrics": {}}
    try:
        ws = Path(os.environ.get("ALPHA_WORKSPACE", "/workspace"))
        dispatch = Path(os.environ.get("ALPHA_DISPATCH_DIR", "/workspace/.dispatched"))
        result = _load_result(ws, jid)
        result["job_id"] = jid  # the runner addresses results by ALPHA_JOB_ID

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
            "payload": {"finished": True, "summary": str(result.get("summary", ""))[:240]},
        },
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
