#!/usr/bin/env python3
"""Stop hook (sub agent): enforce, then push the agent's RunResult + artifacts.

PR2: there is no shared volume. The agent is instructed (CLAUDE.md) to write its full
RunResult to ``$ALPHA_WORKSPACE/result.json`` and its plots under
``$ALPHA_DISPATCH_DIR/artifacts/$ALPHA_JOB_ID/``. This hook reads both, base64-encodes
the (small) artifacts, and POSTs everything to ``/internal/result`` — the runner records
the result, uploads artifacts to GCS, and flips job status.

Idea 2 (active enforcement): the return path used to be pure prose — ~1 in 3 sub-agents
ended their turn without ever writing result.json, and the only recourse was reporting
``failed``. So on the FIRST stop, if the result is structurally unusable (missing /
invalid JSON / a success claim with no target_metric), we BLOCK the stop and hand the
agent a concrete fix instead of giving up. ``stop_hook_active`` guards against an infinite
loop — on the re-stop we fall through to the passive POST below, so a stubborn run still
finalizes rather than wedging. Telemetry: this must NEVER fail the agent.
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
    ".log": "log", ".txt": "log", ".csv": "log", ".json": "log", ".jsonl": "log",
}


def _target_metric(dispatch: Path, jid: str) -> str | None:
    """The plan's target_metric from this sub-agent's dispatch record, if readable."""
    try:
        rec = json.loads((dispatch / f"{jid}.json").read_text())
        tm = (rec.get("plan") or {}).get("target_metric")
        return tm.strip() if isinstance(tm, str) and tm.strip() else None
    except (OSError, json.JSONDecodeError, ValueError, AttributeError):
        return None


def _block_reason(ws: Path, dispatch: Path, jid: str) -> str | None:
    """Return a fix-it message to hand back to the agent if result.json is structurally
    unusable AND a retry could plausibly fix it; else None. Structural only — the softer
    quality contract (baseline, >=2 seeds) is enforced non-destructively at ingress, so we
    don't risk looping the agent over a judgment call it may have made deliberately."""
    rp = ws / "result.json"
    if not rp.exists():
        return ("You have not written /workspace/result.json. Write your full RunResult "
                "now — status/summary/metrics/validated — even a status:\"failed\" one "
                "with diagnostics if the run did not complete. Then stop.")
    try:
        data = json.loads(rp.read_text())
    except (json.JSONDecodeError, ValueError, OSError):
        return ("/workspace/result.json is not valid JSON. Rewrite it as a single JSON "
                "object (status/summary/metrics/...), then stop.")
    if not isinstance(data, dict):
        return ("/workspace/result.json must be a JSON object (not a list/scalar). "
                "Rewrite it, then stop.")
    status = str(data.get("status", "done")).lower()
    validated = bool(data.get("validated", False))
    metrics = data.get("metrics")
    target = _target_metric(dispatch, jid)
    if target and (status == "done" or validated) and isinstance(metrics, dict) \
            and target not in metrics:
        return (f"result.json claims success but metrics is missing the plan's "
                f"target_metric {target!r}. Add metrics[{target!r}] = <your measured "
                f"value> (plus {target}_baseline for a real comparison), then stop.")
    return None


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


_DEBUG_LOG_TAIL = 5 * 1024 * 1024  # ship at most the last 5MB of transcript (POST cap is 10MB)


def _stage_debug_log(hook_in: dict, adir: Path) -> None:
    """Copy the Claude session transcript into the artifacts dir so it ships to GCS like
    any other artifact — giving us a probeable, per-job debug log (every assistant turn,
    tool call, and error) via read_artifacts.py, instead of it living only in ephemeral
    Modal stdout. Best-effort: never fail the agent over a debug convenience. The Stop
    hook input hands us `transcript_path`; we tail it so a huge session stays under the
    POST cap while keeping the most recent (most relevant) turns."""
    tpath = hook_in.get("transcript_path")
    if not tpath:
        return
    try:
        src = Path(tpath)
        if not src.is_file():
            return
        raw = src.read_bytes()
        if len(raw) > _DEBUG_LOG_TAIL:
            raw = b"[... transcript truncated to last 5MB ...]\n" + raw[-_DEBUG_LOG_TAIL:]
        adir.mkdir(parents=True, exist_ok=True)
        (adir / "agent_transcript.jsonl").write_bytes(raw)
    except OSError as err:
        print(f"[finalize] could not stage debug log: {err}", file=sys.stderr)


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
    try:
        hook_in = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        hook_in = {}

    jid = os.environ.get("ALPHA_JOB_ID", "")
    sid = os.environ.get("ALPHA_SESSION_ID", "")
    ws = Path(os.environ.get("ALPHA_WORKSPACE", "/workspace"))
    dispatch = Path(os.environ.get("ALPHA_DISPATCH_DIR", "/workspace/.dispatched"))

    # First stop only: block-and-retry on a structurally unusable result. On the re-stop
    # (stop_hook_active) we never block again — we fall through and POST whatever we have,
    # so the runner always finalizes instead of the agent wedging in a stop loop.
    if not hook_in.get("stop_hook_active"):
        try:
            reason = _block_reason(ws, dispatch, jid)
        except Exception as err:  # noqa: BLE001 — never fail the agent on hook logic
            print(f"[finalize] block-check error: {err}", file=sys.stderr)
            reason = None
        if reason:
            print(json.dumps({"decision": "block", "reason": reason}))
            sys.exit(0)

    result: dict = {"job_id": jid, "status": "failed", "summary": "finalize error", "metrics": {}}
    artifacts: list[dict] = []
    try:
        result = _load_result(ws, jid)
        result["job_id"] = jid
        _stage_debug_log(hook_in, dispatch / "artifacts" / jid)  # probeable debug log
        artifacts = _collect_artifacts(dispatch / "artifacts" / jid)
    except Exception as err:  # noqa: BLE001 — telemetry hook must never fail the agent
        print(f"[finalize] {err}", file=sys.stderr)

    body = {
        "job_id": jid,
        "session_id": sid,
        "status": result.get("status", "done"),
        "summary": str(result.get("summary", "")),
        "metrics": result.get("metrics", {}) or {},
        "idea_id": result.get("idea_id"),
        "validated": bool(result.get("validated", False)),
        "validation_reasoning": str(result.get("validation_reasoning", "")),
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
