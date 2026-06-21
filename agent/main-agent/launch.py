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
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_HOOKS = str(Path(__file__).resolve().parent / ".claude" / "hooks")
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, _HOOKS)
from _push import push  # noqa: E402  (stdlib-only HTTP helper, shared with hooks)
from console_relay import make_console_sender, relay_console  # noqa: E402
from stream_relay import relay  # noqa: E402

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


def _prompt(ctx: dict) -> str:
    goal = (ctx.get("goal") or "").strip()
    base = (
        "You are the research director for an autonomous RL research session.\n\n"
        f"The user's goal:\n{goal}\n\n"
        "This is a NON-INTERACTIVE batch run — there is no human to answer questions. "
        "Read CLAUDE.md and execute the full workflow end to end:\n"
        "  1. State your key assumptions explicitly (do NOT ask the user anything).\n"
        "  2. Use the research skill to produce one ResearchPlan.\n"
        "  3. Dispatch one sub-agent per idea (dispatch-subagents skill).\n"
        "  4. Wait for the children, synthesize their results, and produce Plotly\n"
        "     figures of the findings (plotly-graphs skill).\n"
    )
    loop = ctx.get("loop") if ctx.get("mode") == "autonomous" else None
    if not loop:
        return base + "Run to completion and exit. Never block waiting for user input."

    prior = loop.get("prior_rounds") or []
    prior_lines = "\n".join(
        f"    - round {p.get('round_index')}: best_metric={p.get('best_metric')} "
        f"— {(p.get('summary') or '')[:120]}"
        for p in prior
    ) or "    (none yet — this is the first round)"
    return (
        base
        + (
            f"\nThis is ONE ROUND of an AUTONOMOUS LOOP: round {loop.get('round')} of "
            f"max {loop.get('max_rounds')}"
            + (f" (target metric {loop.get('goal_metric')})" if loop.get("goal_metric") else "")
            + ".\nPrior rounds:\n" + prior_lines + "\n\n"
            "Use the prior rounds to DECIDE this round's direction: deepen the current "
            "approach if it's still gaining, or escalate to a new approach class if it's "
            "plateaued. When the round is done, BEFORE exiting, report it:\n"
            f"    python3 scripts/report_round.py --round-index {loop.get('round')} "
            "--plan-id <plan_id> --best-metric <value> --summary <one line>\n"
            "Then exit. Do NOT loop here yourself — the runner applies the stop policy "
            "and spawns the next round. Run this one round to completion and exit."
        )
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

    session_id = os.environ.get("ALPHA_SESSION_ID", "")
    job_id = os.environ.get("ALPHA_JOB_ID", "")
    try:
        depth = int(os.environ.get("ALPHA_DEPTH") or 0)
    except ValueError:
        depth = 0

    # Spawn claude (don't exec) so we can tail BOTH pipes: stdout's stream-json
    # becomes assistant token/transcript events; stderr (the operational console
    # — diagnostics, tracebacks) used to inherit straight to the Cloud Run log and
    # "die" there. Now we PIPE it and relay each line to the bus as a `console`
    # event, while a tee mirrors it to the real stderr so Cloud Run logs are kept.
    # Both pipes are drained concurrently (a single pipe read would deadlock the
    # other). _prompt is autonomous-loop aware via ctx["loop"].
    argv = _build_argv(_prompt(ctx), model)
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
    )
    # Console pushes go through a non-blocking, drop-oldest sender so a slow/dead
    # runner can never back-pressure the stderr pipe and stall claude.
    sender = make_console_sender(push)
    stderr_thread = threading.Thread(
        target=relay_console,
        args=(proc.stderr, sender.emit),
        kwargs=dict(session_id=session_id, job_id=job_id, depth=depth,
                    stream="stderr", tee=sys.stderr),
        daemon=True,
    )
    stderr_thread.start()
    relay_exc: Exception | None = None
    try:
        relay(proc.stdout, push, session_id=session_id, job_id=job_id, depth=depth)
    except Exception as exc:  # noqa: BLE001 — never lose claude's exit code to a relay error
        relay_exc = exc
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        rc = proc.wait()
        # claude has exited → its stderr pipe is at EOF, so the relay thread
        # finishes promptly; join unbounded, then drain the sender (bounded).
        stderr_thread.join()
        sender.close()
    if relay_exc is not None:
        print(f"[launch] relay error: {relay_exc!r}", file=sys.stderr)
    sys.exit(rc)


if __name__ == "__main__":
    main()
