#!/usr/bin/env python3
"""Stop hook (sub agent): push the agent's RunResult + artifacts to the runner.

PR2: there is no shared volume. The agent is instructed (CLAUDE.md) to write its full
RunResult to ``$ALPHA_WORKSPACE/result.json`` and its plots under
``$ALPHA_DISPATCH_DIR/artifacts/$ALPHA_JOB_ID/``. This hook reads both, base64-encodes
the (small) artifacts, and POSTs everything to ``/internal/result`` — the runner records
the result, uploads artifacts to GCS, and flips job status. If the agent produced
no/invalid result.json, we report ``failed`` so the runner finalizes instead of polling
forever. Telemetry: this must NEVER fail the agent.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _push import push  # noqa: E402

_ARTIFACT_SIZE_CAP = 10 * 1024 * 1024  # match the runner's per-artifact cap
_KIND_BY_SUFFIX = {
    ".png": "plot", ".jpg": "plot", ".jpeg": "plot", ".svg": "plot", ".pdf": "plot",
    ".pt": "checkpoint", ".ckpt": "checkpoint", ".safetensors": "checkpoint",
    ".log": "log", ".txt": "log", ".csv": "log", ".json": "log",
}


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


def _collect_artifacts(adir: Path) -> list[dict]:
    out: list[dict] = []
    if not adir.is_dir():
        return out
    for p in sorted(adir.rglob("*")):
        if not p.is_file():
            continue
        try:
            data = p.read_bytes()
        except OSError:
            continue
        if not data or len(data) > _ARTIFACT_SIZE_CAP:
            continue
        out.append({
            "name": p.name,
            "kind": _KIND_BY_SUFFIX.get(p.suffix.lower(), "other"),
            "b64": base64.b64encode(data).decode("ascii"),
        })
    return out


def main() -> None:
    jid = os.environ.get("ALPHA_JOB_ID", "")
    sid = os.environ.get("ALPHA_SESSION_ID", "")
    result: dict = {"job_id": jid, "status": "failed", "summary": "finalize error", "metrics": {}}
    artifacts: list[dict] = []
    try:
        ws = Path(os.environ.get("ALPHA_WORKSPACE", "/workspace"))
        dispatch = Path(os.environ.get("ALPHA_DISPATCH_DIR", "/workspace/.dispatched"))
        result = _load_result(ws, jid)
        result["job_id"] = jid
        artifacts = _collect_artifacts(dispatch / "artifacts" / jid)
    except Exception as err:  # noqa: BLE001 — telemetry hook must never fail the agent
        print(f"[finalize] {err}", file=sys.stderr)

    body = {
        "job_id": jid,
        "session_id": sid,
        "status": result.get("status", "done"),
        "summary": str(result.get("summary", "")),
        "metrics": result.get("metrics", {}) or {},
        "artifacts": artifacts,
    }
    if result.get("patch"):
        body["patch"] = result["patch"]
    if result.get("base_ref"):
        body["base_ref"] = result["base_ref"]
    # Larger timeout: the runner uploads artifacts to GCS synchronously in the handler.
    push("/internal/result", body, timeout=30.0)
    sys.exit(0)


if __name__ == "__main__":
    main()
