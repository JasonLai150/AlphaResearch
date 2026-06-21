#!/usr/bin/env python3
"""Print a one-line status for each child sub-agent of this main agent.

The main agent runs as a Cloud Run Job with NO shared filesystem to the runner
or to its sub-agents. It therefore CANNOT read a local `.dispatched/` directory
for child results — it must ask the runner over authenticated HTTP.

This script queries:
    GET {ALPHA_INTERNAL_RUNNER_URL}/internal/children/{ALPHA_JOB_ID}
with header `Authorization: Bearer ${ALPHA_INTERNAL_TOKEN}` (timeout 10s).

For each returned row it prints one TAB-separated line to stdout:
    <job_id>\t<status>\t<one-line summary>
where the summary is the first line of row["summary"], newlines collapsed to
spaces and truncated to 120 chars, but only when status == "done"; otherwise
the summary column is "-".

Exit codes:
  0 = queried successfully
  1 = HTTP / connection error (message on stderr)

stdlib only. No infra/ / runner/ / orchestrator/ imports.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

_TIMEOUT_SEC = 10


def _runner_url() -> str:
    return os.environ.get("ALPHA_INTERNAL_RUNNER_URL", "").rstrip("/")


def _one_line_summary(summary: object) -> str:
    if not isinstance(summary, str):
        return "-"
    first = summary.splitlines()[0] if summary.splitlines() else ""
    first = first.replace("\n", " ").replace("\r", " ").strip()
    if len(first) > 120:
        first = first[:120]
    return first if first else "-"


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
    base_url = _runner_url()
    if not base_url:
        print("ALPHA_INTERNAL_RUNNER_URL is not set", file=sys.stderr)
        return 1
    job_id = os.environ.get("ALPHA_JOB_ID", "")
    token = os.environ.get("ALPHA_INTERNAL_TOKEN", "")

    try:
        rows = fetch_children(base_url, job_id, token)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError) as e:
        print(f"failed to query children from runner: {e}", file=sys.stderr)
        return 1

    for row in rows:
        rid = row.get("job_id", "?")
        status = row.get("status", "?")
        if status == "done":
            summary = _one_line_summary(row.get("summary"))
        else:
            summary = "-"
        print(f"{rid}\t{status}\t{summary}")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
