#!/usr/bin/env python3
"""Headless entrypoint for a sub-agent.

A sub-agent gets its task from its dispatch record on the workspace
(``/workspace/.dispatched/$ALPHA_JOB_ID.json``) — not from the runner — so there is
no bootstrap fetch here. This just builds the one-shot prompt and execs `claude -p`
(non-interactive). The agent's CLAUDE.md + hooks (incl. the finalize/Stop hook that
publishes result.json) drive the rest.

stdlib-only by design.
"""

from __future__ import annotations

import os
import sys


def _prompt(jid: str) -> str:
    return (
        "You are a research sub-agent running one idea under a shared, FROZEN plan "
        "scaffold.\n\n"
        f"Read CLAUDE.md, then read your dispatch record at "
        f".dispatched/{jid}.json — it contains the plan and your assigned idea_id.\n\n"
        "This is a NON-INTERACTIVE batch run. Execute your assigned idea against the "
        "frozen scaffold, compare to a baseline, and write your full RunResult to "
        "/workspace/result.json (status/summary/metrics/validated/artifacts). Put any "
        f"plots under /workspace/.dispatched/artifacts/{jid}/. Run to completion and "
        "exit — never block on user input. If the dispatch record is missing or "
        'malformed, write result.json with status:"failed" explaining what was wrong.'
    )


def main() -> None:
    jid = os.environ.get("ALPHA_JOB_ID", "")
    if not jid:
        raise SystemExit("[launch] missing ALPHA_JOB_ID")
    model = os.environ.get("ALPHA_MODEL", "claude-sonnet-4-6")
    print(f"[launch] sub-agent job={jid} model={model}", file=sys.stderr)
    argv = ["claude", "-p", _prompt(jid), "--model", model, "--dangerously-skip-permissions"]
    os.execvp("claude", argv)


if __name__ == "__main__":
    main()
