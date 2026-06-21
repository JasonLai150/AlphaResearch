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
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

_BOOTSTRAP_ATTEMPTS = 5

# Post-deploy smoke (ALPHA_SMOKE=1, set as a per-execution override by
# scripts/verify_deploy.sh): prove the *deployed* image actually boots and can
# reach Anthropic, using the real container + service account + mounted secrets —
# without a runner, a session token, or a 4h agent run. A created Cloud Run Job is
# never exercised until the first real chat, so this is the only quick, high-fidelity
# signal that the agent image isn't silently broken on GCP.
_SMOKE_MODEL = "claude-haiku-4-5-20251001"  # cheapest model; the round-trip is what matters
_SMOKE_TIMEOUT_S = 120


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


def _smoke() -> None:
    """Real `claude` round-trip inside the deployed container. Exits 0 only if the
    Claude Code CLI is installed, ANTHROPIC_API_KEY is mounted+valid, and network
    egress to Anthropic works. The process exit code is the Cloud Run execution's
    exit code, so `gcloud run jobs execute --wait` surfaces any failure directly."""
    problems = []
    if shutil.which("claude") is None:
        problems.append("`claude` not on PATH (broken agent image)")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        problems.append("ANTHROPIC_API_KEY missing (secret not mounted)")
    if problems:
        raise SystemExit("[smoke] FAIL: " + "; ".join(problems))

    model = os.environ.get("ALPHA_MODEL") or _SMOKE_MODEL
    print(f"[smoke] claude round-trip model={model} timeout={_SMOKE_TIMEOUT_S}s", file=sys.stderr)
    try:
        r = subprocess.run(
            ["claude", "-p", "Respond with exactly: SMOKE_OK",
             "--model", model, "--dangerously-skip-permissions"],
            capture_output=True, text=True, timeout=_SMOKE_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        raise SystemExit(f"[smoke] FAIL: claude timed out after {_SMOKE_TIMEOUT_S}s (egress/API stall)")
    tail = ((r.stdout or "") + (r.stderr or ""))[-800:]
    if r.returncode != 0:
        raise SystemExit(f"[smoke] FAIL: claude exited {r.returncode}\n{tail}")
    if "SMOKE_OK" not in (r.stdout or ""):
        raise SystemExit(f"[smoke] FAIL: unexpected model output\n{tail}")
    print("[smoke] OK — CLI + API key + egress verified inside the deployed image", file=sys.stderr)


def main() -> None:
    if os.environ.get("ALPHA_SMOKE", "").strip().lower() in ("1", "true", "yes"):
        _smoke()
        return

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
