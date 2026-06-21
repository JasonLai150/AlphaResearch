#!/usr/bin/env python3
"""Print the artifacts produced by a single child sub-agent as pretty JSON.

The main agent runs as a Cloud Run Job with NO shared filesystem to its
sub-agents, so artifacts are fetched from the runner over authenticated HTTP.

It queries:
    GET {ALPHA_INTERNAL_RUNNER_URL}/internal/children/{ALPHA_JOB_ID}/artifacts
with header `Authorization: Bearer ${ALPHA_INTERNAL_TOKEN}`. The response is a
JSON object mapping child job_id -> list of artifact dicts. This script prints
(indent=2) the list for the requested job_id, or [] if absent.

Usage:
    read_artifacts.py <job_id>

Exit codes:
  0 = printed artifacts (possibly an empty list)
  2 = wrong number of arguments (usage on stderr)

On HTTP/connection error we print "[]" to stdout and exit 0 so the agent is not
blocked by a flaky runner.

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


def fetch_artifacts(base_url: str, parent_job_id: str, token: str) -> dict:
    url = f"{base_url}/internal/children/{parent_job_id}/artifacts"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:
        body = resp.read().decode("utf-8")
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object, got {type(data).__name__}")
    return data


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: read_artifacts.py <job_id>", file=sys.stderr)
        return 2
    job_id = argv[0]

    base_url = _runner_url()
    parent_job_id = os.environ.get("ALPHA_JOB_ID", "")
    token = os.environ.get("ALPHA_INTERNAL_TOKEN", "")

    if not base_url:
        # Local-only / misconfigured: don't block the agent.
        print("[]")
        return 0

    try:
        data = fetch_artifacts(base_url, parent_job_id, token)
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        print("[]")
        return 0

    artifacts = data.get(job_id, [])
    print(json.dumps(artifacts, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
