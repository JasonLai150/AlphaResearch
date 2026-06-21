#!/usr/bin/env python3
"""Report this round's outcome to the runner (autonomous loops).

The main agent runs one ROUND of an autonomous loop. Before it exits, it calls
this to POST the round's best metric + plan to the runner, which reads it to apply
the stop policy and decide whether to spawn the next round.

    report_round.py --round-index N [--plan-id ID] [--best-metric F] [--summary S]

Best-effort by design: if the POST fails, exit 0 anyway — the runner has a
backstop that counts an unreported round, so a flaky network must never wedge the
loop. stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

_TIMEOUT_SEC = 10


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Report an autonomous-loop round to the runner.")
    ap.add_argument("--round-index", type=int, required=True)
    ap.add_argument("--plan-id", default=None)
    ap.add_argument("--best-metric", type=float, default=None)
    ap.add_argument("--summary", default="")
    args = ap.parse_args(argv)

    base_url = os.environ.get("ALPHA_INTERNAL_RUNNER_URL", "").rstrip("/")
    token = os.environ.get("ALPHA_INTERNAL_TOKEN", "")
    sid = os.environ.get("ALPHA_SESSION_ID", "")
    jid = os.environ.get("ALPHA_JOB_ID", "")
    if not base_url or not sid:
        print("[report_round] missing runner url / session id; skipping", file=sys.stderr)
        return 0

    body = json.dumps({
        "session_id": sid, "job_id": jid, "round_index": args.round_index,
        "plan_id": args.plan_id, "best_metric": args.best_metric, "summary": args.summary,
    }).encode()
    req = urllib.request.Request(
        f"{base_url}/internal/loop/round", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC):
            pass
    except (urllib.error.URLError, OSError) as err:
        # Best-effort: the runner's backstop counts the round even without this.
        print(f"[report_round] post failed ({err!r}); runner backstop will count it",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
