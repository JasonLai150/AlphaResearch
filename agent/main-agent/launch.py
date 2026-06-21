#!/usr/bin/env python3
"""Headless entrypoint for the main agent (Cloud Run Job).

Cloud Run Jobs have no TTY/stdin, so the interactive `claude` REPL can't self-drive.
This launcher fetches the session goal from the runner (GET /internal/bootstrap,
token->session) and spawns `claude -p` (non-interactive print mode) in stream-json
mode, piping its stdout through the stream relay so assistant text deltas reach
the runner live.

stdlib-only by design (the image excludes infra/ and purges curl). Mirrors
.claude/hooks/_push.py.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_HOOKS = str(Path(__file__).resolve().parent / ".claude" / "hooks")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, _HOOKS)
from _push import push  # noqa: E402  (stdlib-only HTTP helper, shared with hooks)
from stream_relay import relay  # noqa: E402

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


def _build_argv(prompt: str, model: str) -> list[str]:
    """claude in streaming print mode: emit per-token JSON so the relay can
    forward assistant text live. --verbose is required with -p + stream-json."""
    return [
        "claude",
        "-p",
        prompt,
        "--model",
        model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--dangerously-skip-permissions",
    ]


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

    session_id = os.environ.get("ALPHA_SESSION_ID", "")
    job_id = os.environ.get("ALPHA_JOB_ID", "")
    try:
        depth = int(os.environ.get("ALPHA_DEPTH") or 0)
    except ValueError:
        depth = 0

    # Spawn claude (don't exec) so we can tail its stream-json stdout and relay
    # assistant text deltas to the runner. stderr inherits -> Cloud Run logs.
    argv = _build_argv(_prompt(goal), model)
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, text=True, bufsize=1)
    try:
        relay(proc.stdout, push, session_id=session_id, job_id=job_id, depth=depth)
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        rc = proc.wait()
    sys.exit(rc)


if __name__ == "__main__":
    main()
