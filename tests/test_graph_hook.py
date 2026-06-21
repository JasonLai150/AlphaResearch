"""Tests for the validate_graph_spec PostToolUse hook (main agent).

When the agent Writes/Edits a GraphSpec under .graphs/specs/*.json, the hook
validates it against the GraphSpec schema and — on failure — feeds the schema
errors back so the agent rewrites it correctly. Non-graph writes pass untouched.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _REPO_ROOT / "agent" / "main-agent" / ".claude" / "hooks" / "validate_graph_spec.py"


def _run(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=15,
    )


def _valid_spec() -> dict:
    return {
        "id": "g1", "kind": "line", "title": "t", "x_label": "x", "y_label": "y",
        "series": [{"name": "a", "x": [0, 1], "y": [0.0, 1.0]}],
    }


def _write_spec(tmp_path: Path, content: dict | str) -> Path:
    specs = tmp_path / ".graphs" / "specs"
    specs.mkdir(parents=True)
    f = specs / "g1.json"
    f.write_text(content if isinstance(content, str) else json.dumps(content))
    return f


def test_valid_spec_passes_silently(tmp_path):
    f = _write_spec(tmp_path, _valid_spec())
    proc = _run({"tool_name": "Write", "tool_input": {"file_path": str(f)}})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""  # nothing to say


def test_malformed_spec_feeds_back_error(tmp_path):
    bad = _valid_spec()
    bad["series"] = []  # a graph needs >=1 series
    f = _write_spec(tmp_path, bad)
    proc = _run({"tool_name": "Write", "tool_input": {"file_path": str(f)}})
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    blob = json.dumps(out).lower()
    assert "series" in blob  # the error names the offending field
    assert out.get("hookSpecificOutput", {}).get("additionalContext")


def test_invalid_json_feeds_back_error(tmp_path):
    f = _write_spec(tmp_path, "{not valid json")
    proc = _run({"tool_name": "Write", "tool_input": {"file_path": str(f)}})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() != ""  # complained


def test_non_graph_write_ignored(tmp_path):
    other = tmp_path / "notes.json"
    other.write_text("{not even checked}")
    proc = _run({"tool_name": "Write", "tool_input": {"file_path": str(other)}})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_non_write_tool_ignored(tmp_path):
    f = _write_spec(tmp_path, _valid_spec())
    proc = _run({"tool_name": "Bash", "tool_input": {"command": f"cat {f}"}})
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


def test_relative_path_is_matched_and_validated(tmp_path):
    # The agent writes a RELATIVE path (.graphs/specs/<id>.json) from /workspace.
    # The hook must still recognize and validate it.
    bad = _valid_spec()
    bad["series"] = []
    _write_spec(tmp_path, bad)  # writes tmp_path/.graphs/specs/g1.json
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps({"tool_name": "Write",
                          "tool_input": {"file_path": ".graphs/specs/g1.json"}}),
        capture_output=True, text=True, timeout=15, cwd=str(tmp_path),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() != "", "relative-path spec write was not validated"
