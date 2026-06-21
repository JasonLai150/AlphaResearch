#!/usr/bin/env python3
"""PreCompact hook: preserve load-bearing state before the context is compacted.

A long research session gets compacted, and the director's in-context reasoning
(what it dispatched, what came back, decisions + why) would be lossily summarized.
Before that, this hook:

  1. Copies the full transcript to .dispatched/snapshots/precompact-<n>.jsonl so
     nothing is truly lost — the agent can grep it after compaction.
  2. Appends a marker to session_state.md listing the dispatched children, so the
     agent's durable working journal stays current.
  3. Reminds the agent (additionalContext) to rebuild state from disk + runner
     status rather than from its (now-compacted) memory.

stdlib-only. exit 0 always — a hook crash must never wedge the agent.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


def _workspace() -> Path:
    return Path(os.environ.get("ALPHA_WORKSPACE") or Path(__file__).resolve().parents[2])


def _dispatch_dir(ws: Path) -> Path:
    return Path(os.environ.get("ALPHA_DISPATCH_DIR") or (ws / ".dispatched"))


def _dispatched_children(dispatch_dir: Path) -> list[str]:
    """Job ids of dispatched children (every .dispatched/*.json except plan.json)."""
    if not dispatch_dir.is_dir():
        return []
    return sorted(
        f.stem for f in dispatch_dir.glob("*.json") if f.stem != "plan"
    )


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        payload = {}

    ws = _workspace()
    dispatch_dir = _dispatch_dir(ws)
    snaps = dispatch_dir / "snapshots"

    # 1. snapshot the transcript (best-effort)
    snapshot_path = None
    transcript = payload.get("transcript_path") or ""
    try:
        snaps.mkdir(parents=True, exist_ok=True)
        n = len(list(snaps.glob("precompact-*.jsonl"))) + 1
        if transcript and Path(transcript).is_file():
            snapshot_path = snaps / f"precompact-{n}.jsonl"
            shutil.copyfile(transcript, snapshot_path)
    except OSError:
        pass

    # 2. record dispatched children + the snapshot pointer in the working journal
    children = _dispatched_children(dispatch_dir)
    trigger = payload.get("trigger", "?")
    note = (
        f"\n## context compaction ({trigger})\n"
        f"- dispatched children at compaction: {children or 'none'}\n"
        f"- transcript snapshot: {snapshot_path if snapshot_path else 'unavailable'}\n"
        "- on resume: rebuild state from session_state.md + `check_children.py`, "
        "not from memory.\n"
    )
    try:
        with (ws / "session_state.md").open("a") as fh:
            fh.write(note)
    except OSError:
        pass

    reason = (
        "Context was compacted. Re-read session_state.md and run check_children.py to "
        "rebuild what you've dispatched and what has returned before continuing — your "
        "in-context history was summarized and may be lossy. Full pre-compaction "
        f"transcript: {snapshot_path if snapshot_path else '(snapshot unavailable)'}."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreCompact",
            "additionalContext": reason,
        },
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
