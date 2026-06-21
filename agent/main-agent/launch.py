#!/usr/bin/env python3
"""Headless entrypoint for the main agent (Cloud Run Job).

Cloud Run Jobs have no TTY/stdin, so the interactive `claude` REPL can't self-drive.
This launcher fetches the session goal from the runner (GET /internal/bootstrap,
token->session) and execs `claude -p` (non-interactive print mode). The agent's
CLAUDE.md + .claude/settings.json (skills, hooks) drive everything after that;
telemetry flows back via the hooks, not this process's stdout.

stdlib-only by design (the image excludes infra/ and purges curl). Mirrors
.claude/hooks/_push.py.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

_BOOTSTRAP_ATTEMPTS = 5


def _bootstrap(runner_url: str, token: str) -> dict:
    url = runner_url.rstrip("/") + "/internal/bootstrap"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    last: Exception | None = None
    for i in range(_BOOTSTRAP_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, OSError, ValueError) as err:
            last = err
            time.sleep(min(2 ** i, 8))  # runner may still be cold on first try
    raise SystemExit(f"[launch] bootstrap failed after {_BOOTSTRAP_ATTEMPTS}: {last!r}")


def _prompt(goal: str) -> str:
    return (
        "You are the research director for an autonomous RL research session.\n\n"
        f"The user's goal:\n{goal}\n\n"
        "This is a NON-INTERACTIVE batch run — there is no human to answer questions. "
        "Read CLAUDE.md and execute the full workflow end to end:\n"
        "  1. State your key assumptions explicitly (do NOT ask the user anything).\n"
        "  2. Use the research skill to produce one ResearchPlan.\n"
        "  3. Dispatch one sub-agent per idea (dispatch-subagents skill).\n"
        "  4. Wait for the children, then synthesize their results.\n"
        "Run to completion and exit. Never block waiting for user input."
    )


def main() -> None:
    runner_url = os.environ.get("ALPHA_INTERNAL_RUNNER_URL", "")
    token = os.environ.get("ALPHA_INTERNAL_TOKEN", "")
    model = os.environ.get("ALPHA_MODEL", "claude-sonnet-4-6")
    if not runner_url or not token:
        raise SystemExit("[launch] missing ALPHA_INTERNAL_RUNNER_URL / ALPHA_INTERNAL_TOKEN")

    ctx = _bootstrap(runner_url, token)
    goal = (ctx.get("goal") or "").strip()
    if not goal:
        raise SystemExit("[launch] bootstrap returned an empty goal")
    print(f"[launch] mode={ctx.get('mode')} goal={goal[:120]!r}", file=sys.stderr)

    os.environ["ALPHA_NONINTERACTIVE"] = "1"  # CLAUDE.md gates its clarifying-Q step on this
    argv = ["claude", "-p", _prompt(goal), "--model", model, "--dangerously-skip-permissions"]
    os.execvp("claude", argv)  # replace this process; claude inherits cwd=/workspace + env


if __name__ == "__main__":
    main()
