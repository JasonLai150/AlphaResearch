#!/usr/bin/env python3
"""Headless entrypoint for a sub-agent.

A sub-agent gets its task from its dispatch record on the workspace
(``/workspace/.dispatched/$ALPHA_JOB_ID.json``) — not from the runner — so there is
no bootstrap fetch here. This builds the one-shot prompt and spawns `claude -p`
(non-interactive).

Unlike a plain exec, we spawn claude so we can tail BOTH of its pipes and relay
every line to the runner as a `console` event tagged with this sub-agent's
session/job/depth. The trainer's stdout and claude's stderr used to inherit to
the Modal log and "die" there — now they reach the frontend's per-subagent
console, while a tee preserves the Modal log. The agent's CLAUDE.md + hooks
(incl. the finalize/Stop hook that POSTs result.json) drive the rest.

stdlib-only by design.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE / ".claude" / "hooks"))
from _push import push  # noqa: E402  (stdlib-only HTTP helper, shared with hooks)
from console_relay import make_console_sender, relay_console  # noqa: E402


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
    session_id = os.environ.get("ALPHA_SESSION_ID", "")
    try:
        depth = int(os.environ.get("ALPHA_DEPTH") or 1)
    except ValueError:
        depth = 1
    model = os.environ.get("ALPHA_MODEL", "claude-sonnet-4-6")
    print(f"[launch] sub-agent job={jid} model={model}", file=sys.stderr)

    argv = ["claude", "-p", _prompt(jid), "--model", model, "--dangerously-skip-permissions"]
    # Spawn (don't exec) so both pipes can stream to the per-subagent console.
    # Drain stdout in a thread + stderr in the main thread (reading a single pipe
    # would deadlock the other); tee each back to the real fd so Modal logs persist.
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
    )
    # One non-blocking sender feeds both pipes' console pushes, so a slow/dead
    # runner can never back-pressure either pipe and stall the trainer/claude.
    sender = make_console_sender(push)
    stdout_thread = threading.Thread(
        target=relay_console,
        args=(proc.stdout, sender.emit),
        kwargs=dict(session_id=session_id, job_id=jid, depth=depth,
                    stream="stdout", tee=sys.stdout),
        daemon=True,
    )
    stdout_thread.start()
    try:
        relay_console(proc.stderr, sender.emit, session_id=session_id, job_id=jid,
                      depth=depth, stream="stderr", tee=sys.stderr)
    finally:
        if proc.stdout is not None:
            proc.stdout.close()
        rc = proc.wait()
        stdout_thread.join()  # stdout at EOF once claude exits → finishes promptly
        sender.close()        # drain queued console (bounded)
    sys.exit(rc)


if __name__ == "__main__":
    main()
