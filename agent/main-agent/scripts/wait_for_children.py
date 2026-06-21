#!/usr/bin/env python3
"""Block until a set of child sub-agents reach a terminal state (done/failed).

The main agent runs as a Cloud Run Job with NO shared filesystem to its
sub-agents, so it polls the runner over authenticated HTTP rather than watching
local files.

Each poll it queries:
    GET {ALPHA_INTERNAL_RUNNER_URL}/internal/children/{ALPHA_JOB_ID}
with header `Authorization: Bearer ${ALPHA_INTERNAL_TOKEN}`, builds the set of
job_ids whose row is terminal (row["done"] is true OR status in
{done,failed,cancelled}), removes those from the pending set, then sleeps
`--poll-sec`.

Usage:
    wait_for_children.py JOB_ID [JOB_ID ...] [--timeout 1800] [--poll-sec 5.0]

Exit codes:
  0 = all requested children reached a terminal state
  1 = configuration error (e.g. ALPHA_INTERNAL_RUNNER_URL unset)
  2 = timeout (still-pending ids printed to stderr)

A transient HTTP error during a poll is treated as "no progress this round":
we do not crash, we keep polling until the deadline.

stdlib only. No infra/ / runner/ / orchestrator/ imports.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

_TIMEOUT_SEC = 10


def _runner_url() -> str:
    return os.environ.get("ALPHA_INTERNAL_RUNNER_URL", "").rstrip("/")


def _is_terminal(row: dict) -> bool:
    if row.get("done") is True:
        return True
    # "cancelled" is terminal but carries NO RunResult (so done=False) — the runner
    # reaps orphaned/parent-terminal children without writing one (see
    # runner/loops.py:_cancel_orphans_if_terminal). Omitting it here made the main
    # agent block on a cancelled child until --timeout instead of synthesizing.
    return row.get("status") in {"done", "failed", "cancelled"}


def fetch_children(base_url: str, job_id: str, token: str) -> list:
    url = f"{base_url}/internal/children/{job_id}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON list of children, got {type(data).__name__}")
    return data


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Wait for child sub-agents to finish.")
    ap.add_argument("job_ids", nargs="+", help="job ids to wait on")
    # Default matches the Modal sub-agent cap (2h): a sub-agent training on a CPU learner
    # can run far longer than the old 30min default, and giving up early is exactly what
    # excluded slow children from synthesis. Pass plan.wait_timeout_seconds() explicitly
    # when you know the plan's wall-clock budget.
    ap.add_argument("--timeout", type=int, default=7200, help="overall timeout in seconds")
    ap.add_argument("--poll-sec", type=float, default=5.0, help="seconds between polls")
    args = ap.parse_args(argv)

    base_url = _runner_url()
    if not base_url:
        print("ALPHA_INTERNAL_RUNNER_URL is not set", file=sys.stderr)
        return 1
    parent_job_id = os.environ.get("ALPHA_JOB_ID", "")
    token = os.environ.get("ALPHA_INTERNAL_TOKEN", "")

    pending = set(args.job_ids)
    deadline = time.monotonic() + args.timeout

    while pending:
        try:
            rows = fetch_children(base_url, parent_job_id, token)
            terminal = {
                row.get("job_id")
                for row in rows
                if isinstance(row, dict) and _is_terminal(row)
            }
            pending -= terminal
        except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
            # Transient: treat as no progress this round, keep polling.
            pass

        if not pending:
            break

        if time.monotonic() >= deadline:
            print(f"timeout waiting for: {sorted(pending)}", file=sys.stderr)
            return 2

        time.sleep(args.poll_sec)

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
