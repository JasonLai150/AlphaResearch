#!/usr/bin/env python3
"""PostToolUse hook: cap oversized output from the child-reading Bash scripts.

The director reads sub-agent results over Bash (read_artifacts.py /
check_children.py). A pathological result (huge artifact list, runaway summary)
would dump arbitrary text into the director's context and crowd out its
reasoning. This is the Bash analogue of cap_web_fetch.py.

NOTE this is a *backstop*. A PostToolUse hook runs after the output is already
admitted, so the real cap lives at the source (inside those scripts); this catches
what slips through and tells the agent how to narrow the query.

Deliberately does NOT cap wait_for_children.py — its stdout (incl. a timeout
signal) must reach the agent intact. exit 0 always.
"""

from __future__ import annotations

import json
import sys

MAX_CHARS = 20_000  # ~5k tokens; healthy multi-child reads are well under this
_WATCHED = ("read_artifacts.py", "check_children.py")


def _response_text(tool_response: object) -> str:
    """Pull the visible text out of the several shapes a Bash result can take."""
    if isinstance(tool_response, str):
        return tool_response
    if isinstance(tool_response, dict):
        if isinstance(tool_response.get("text"), str):
            return tool_response["text"]
        if "stdout" in tool_response or "stderr" in tool_response:
            return f"{tool_response.get('stdout', '')}{tool_response.get('stderr', '')}"
        content = tool_response.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                b.get("text", "") for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
    return ""


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)

    if payload.get("tool_name") != "Bash":
        sys.exit(0)

    command = (payload.get("tool_input") or {}).get("command") or ""
    script = next((s for s in _WATCHED if s in command), None)
    if script is None:
        sys.exit(0)

    text = _response_text(payload.get("tool_response"))
    if len(text) <= MAX_CHARS:
        sys.exit(0)

    reason = (
        f"bash-cap hook: {script} returned {len(text)} chars (cap={MAX_CHARS}); "
        "truncated to protect the context budget. Narrow the query — call "
        "read_artifacts.py for one job_id at a time, or re-run check_children.py "
        "for just the status line you need."
    )
    truncated = text[:MAX_CHARS] + f"\n... [TRUNCATED at {MAX_CHARS} chars] ..."
    out = {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": truncated,
        },
    }
    print(json.dumps(out))
    sys.exit(0)


if __name__ == "__main__":
    main()
