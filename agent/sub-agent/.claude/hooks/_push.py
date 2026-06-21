#!/usr/bin/env python3
"""Shared HTTP push helper for telemetry hooks.

stdlib-only by design: the agent container images deliberately exclude
``infra/``, ``runner/`` and ``orchestrator/``. Do NOT import from those here.
Hooks are telemetry: this function must NEVER raise.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

# SEV-13: bounded retry — runs inline in the agent loop, so keep it tiny.
_MAX_ATTEMPTS = 2
_BACKOFF_SECONDS = 0.25


def push(path: str, body: dict, timeout: float = 1.0) -> None:
    runner_url = os.environ.get("ALPHA_INTERNAL_RUNNER_URL", "")
    token = os.environ.get("ALPHA_INTERNAL_TOKEN", "")
    if not runner_url or not token:
        return

    url = runner_url.rstrip("/") + path
    data = json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    last_err: Exception | None = None
    for attempt in range(_MAX_ATTEMPTS):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout):
                return  # 2xx/3xx -> success
        except urllib.error.HTTPError as err:
            last_err = err
            if not (500 <= err.code < 600):  # don't retry 4xx
                break
        except (urllib.error.URLError, OSError, TimeoutError) as err:
            last_err = err

        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_BACKOFF_SECONDS)

    if last_err is not None:
        print(f"[hook push] {last_err}", file=sys.stderr)
