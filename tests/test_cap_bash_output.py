"""Tests for the cap_bash_output PostToolUse hook (main agent).

The director reads sub-agent results over Bash (read_artifacts.py /
check_children.py). A pathological result can dump arbitrary text into the
director's context. This backstop caps the output of those specific scripts and
tells the agent how to narrow the query. It must NOT cap wait_for_children.py
(whose empty/timeout stdout is a signal) or unrelated commands.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _REPO_ROOT / "agent" / "main-agent" / ".claude" / "hooks" / "cap_bash_output.py"

_BIG = "x" * 50_000
_SMALL = "y" * 100


def _run(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=15,
    )


def _bash(command: str, response) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command},
            "tool_response": response}


def test_big_read_artifacts_output_is_capped():
    proc = _run(_bash("python3 scripts/read_artifacts.py j_a", {"type": "text", "text": _BIG}))
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert len(ctx) < len(_BIG)          # actually shrunk
    assert "read_artifacts.py" in out["reason"]


def test_small_output_passes_silently():
    proc = _run(_bash("python3 scripts/read_artifacts.py j_a", {"type": "text", "text": _SMALL}))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_check_children_is_also_capped():
    proc = _run(_bash("python3 scripts/check_children.py", {"type": "text", "text": _BIG}))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() != ""


def test_wait_for_children_is_not_capped():
    # Its (possibly large) stdout is a signal; capping it would hide timeouts.
    proc = _run(_bash("python3 scripts/wait_for_children.py j_a j_b",
                      {"type": "text", "text": _BIG}))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_unrelated_big_command_not_capped():
    proc = _run(_bash("ls -laR /workspace", {"type": "text", "text": _BIG}))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_non_bash_tool_ignored():
    proc = _run({"tool_name": "Read", "tool_input": {"file_path": "/x"},
                 "tool_response": {"type": "text", "text": _BIG}})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_handles_stdout_dict_shape():
    # Be robust to a {stdout,stderr} response shape too, not only {type,text}.
    proc = _run(_bash("python3 scripts/read_artifacts.py j_a",
                      {"stdout": _BIG, "stderr": ""}))
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() != ""
