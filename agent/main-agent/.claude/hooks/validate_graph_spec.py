#!/usr/bin/env python3
"""PostToolUse hook: validate GraphSpec files the agent writes.

When the agent Writes/Edits a graph spec under ``.graphs/specs/*.json``, this
re-parses it against the GraphSpec schema (scripts/schemas.py). If it's malformed
the hook feeds the schema errors back as additional context so the agent fixes
the spec before it ever reaches render_graph.py — keeping "the right format"
enforced rather than hoped for.

Non-graph writes and non-Write tools pass through silently. exit 0 always (a hook
crash must never wedge the agent).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

_SPEC_MARKER = "/.graphs/specs/"


def _is_graph_spec(file_path: str) -> bool:
    # The agent writes a RELATIVE path from /workspace (".graphs/specs/<id>.json").
    # Prepend "/" so the marker matches relative and absolute paths alike.
    p = file_path.replace("\\", "/")
    if p.startswith("./"):
        p = p[2:]
    if not p.startswith("/"):
        p = "/" + p
    return _SPEC_MARKER in p and p.endswith(".json")


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    if payload.get("tool_name") not in ("Write", "Edit"):
        sys.exit(0)

    file_path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not _is_graph_spec(file_path):
        sys.exit(0)

    try:
        from pydantic import ValidationError
        from schemas import GraphSpec
    except ImportError:
        sys.exit(0)  # schema unavailable — don't block the agent

    try:
        raw = Path(file_path).read_text()
    except OSError:
        sys.exit(0)

    try:
        GraphSpec.model_validate_json(raw)
        sys.exit(0)  # valid — say nothing
    except (ValidationError, ValueError) as err:
        reason = (
            f"graph-spec hook: {file_path} is not a valid GraphSpec and will NOT render. "
            f"Fix it to match scripts/schemas.py:GraphSpec (a 'series' list of "
            f"{{name, x, y, error_y?}} with equal-length x/y, a non-empty title, and "
            f"kind in line|bar|scatter). Validation error:\n{err}"
        )

    out = {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": reason,
        },
    }
    print(json.dumps(out))
    sys.exit(0)


if __name__ == "__main__":
    main()
