"""Tests for the precompact_snapshot hook (main agent).

A long research session WILL get its context compacted. Before that happens this
PreCompact hook (1) copies the full transcript to disk so nothing is lost, (2)
records the dispatched children + a pointer in session_state.md, and (3) reminds
the agent to rebuild state from disk afterwards. exit 0 always.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _REPO_ROOT / "agent" / "main-agent" / ".claude" / "hooks" / "precompact_snapshot.py"


def _run(payload: dict, workspace: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["ALPHA_WORKSPACE"] = str(workspace)
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=15, env=env,
    )


def _workspace(tmp_path: Path, *, with_dispatch=True) -> tuple[Path, Path]:
    ws = tmp_path / "workspace"
    ws.mkdir()
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text('{"role":"user","content":"hi"}\n{"role":"assistant"}\n')
    if with_dispatch:
        d = ws / ".dispatched"
        d.mkdir()
        (d / "plan.json").write_text("{}")          # not a child
        (d / "j_aaa.json").write_text('{"job_id":"j_aaa"}')
        (d / "j_bbb.json").write_text('{"job_id":"j_bbb"}')
    return ws, transcript


def test_snapshots_the_transcript(tmp_path):
    ws, transcript = _workspace(tmp_path)
    proc = _run({"hook_event_name": "PreCompact", "transcript_path": str(transcript),
                 "trigger": "auto"}, ws)
    assert proc.returncode == 0, proc.stderr
    snaps = list((ws / ".dispatched" / "snapshots").glob("precompact-*.jsonl"))
    assert len(snaps) == 1
    assert snaps[0].read_text() == transcript.read_text()


def test_records_dispatched_children_in_state(tmp_path):
    ws, transcript = _workspace(tmp_path)
    proc = _run({"hook_event_name": "PreCompact", "transcript_path": str(transcript)}, ws)
    assert proc.returncode == 0, proc.stderr
    state = (ws / "session_state.md").read_text()
    assert "j_aaa" in state and "j_bbb" in state
    assert "plan" not in state.split("dispatched")[-1].split("\n")[0]  # plan.json excluded


def test_outputs_reconstruct_reminder(tmp_path):
    ws, transcript = _workspace(tmp_path)
    proc = _run({"hook_event_name": "PreCompact", "transcript_path": str(transcript)}, ws)
    out = json.loads(proc.stdout)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "session_state.md" in ctx
    assert out["hookSpecificOutput"]["hookEventName"] == "PreCompact"


def test_missing_transcript_is_safe(tmp_path):
    ws, _ = _workspace(tmp_path)
    proc = _run({"hook_event_name": "PreCompact", "transcript_path": str(tmp_path / "nope.jsonl")},
                ws)
    assert proc.returncode == 0, proc.stderr
    assert (ws / "session_state.md").exists()  # still records the event


def test_no_dispatch_dir_is_safe(tmp_path):
    ws, transcript = _workspace(tmp_path, with_dispatch=False)
    proc = _run({"hook_event_name": "PreCompact", "transcript_path": str(transcript)}, ws)
    assert proc.returncode == 0, proc.stderr
