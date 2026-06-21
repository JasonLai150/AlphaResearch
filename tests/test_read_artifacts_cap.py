"""The source-side cap in read_artifacts.py.

A PostToolUse hook runs too late to un-spend context, so read_artifacts caps its
own output: full pretty JSON when small, a metadata-only trimmed view with a
notice when the artifact list would blow the director's window.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_RA = (
    Path(__file__).resolve().parent.parent
    / "agent" / "main-agent" / "scripts" / "read_artifacts.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("_read_artifacts", _RA)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ra = _load()


def test_small_list_returns_full_json():
    arts = [{"name": "loss.png", "kind": "plot", "url": "gs://b/loss.png", "caption": "c"}]
    out = ra._render_artifacts(arts, max_chars=20_000)
    assert json.loads(out) == arts  # untouched, fully parseable


def test_big_list_is_capped_with_notice():
    arts = [
        {"name": f"a{i}.png", "kind": "plot", "url": f"gs://b/a{i}.png",
         "caption": "x" * 500}
        for i in range(1000)
    ]
    out = ra._render_artifacts(arts, max_chars=20_000)
    assert len(out) <= 20_000 + 300  # bounded (+ notice slack)
    assert "of 1000 artifacts" in out  # tells the agent what was dropped


def test_empty_list():
    assert json.loads(ra._render_artifacts([], max_chars=20_000)) == []
