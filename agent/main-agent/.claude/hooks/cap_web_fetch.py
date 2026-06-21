#!/usr/bin/env python3
"""PostToolUse hook: block oversized WebFetch / WebSearch responses.

We can't know page size before the request, so this is post-tool: if the
response text would dump more than MAX_CHARS into the model context, we BLOCK
the response from being passed to the model and tell the agent to fetch a more
specific URL. The agent sees the reason in the next turn.

This is the "hooks should check that any website reads don't load too much
information" rule from the brief.

Stdin (Claude Code Hooks v1 PostToolUse payload):
    {
      "session_id": "...",
      "tool_name": "WebFetch",
      "tool_input": {...},
      "tool_response": {"content": [{"type":"text","text":"..."}, ...]}
    }

We use Claude Code's documented JSON output for PostToolUse to surface the
block reason as additional context.
"""

from __future__ import annotations

import json
import sys

# ~12 KB ≈ ~3k tokens of English. Enough for a focused doc page; rejects whole-
# page dumps that blow context.
MAX_CHARS = 12_000


def _response_text_length(tool_response: object) -> int:
    if isinstance(tool_response, dict):
        content = tool_response.get("content")
        if isinstance(content, list):
            total = 0
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    total += len(block.get("text") or "")
            return total
        if isinstance(content, str):
            return len(content)
    if isinstance(tool_response, str):
        return len(tool_response)
    return 0


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        sys.exit(0)

    if payload.get("tool_name") not in ("WebFetch", "WebSearch"):
        sys.exit(0)

    size = _response_text_length(payload.get("tool_response"))
    if size <= MAX_CHARS:
        sys.exit(0)

    url = (payload.get("tool_input") or {}).get("url") or "<unknown>"
    reason = (
        f"web-cap hook: response from {url} was {size} chars "
        f"(cap={MAX_CHARS}). Tool result blocked to preserve context budget. "
        "Fetch a more specific URL (deep-link to the relevant section), or "
        "use WebSearch to summarize across pages instead."
    )
    # PostToolUse documented JSON envelope: `decision: block` is shown to the
    # model as an additional system message and prevents the tool response
    # from being added to the conversation.
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
