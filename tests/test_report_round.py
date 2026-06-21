"""agent/main-agent/scripts/report_round.py — the agent reports its round's
outcome to the runner before exiting, so the runner can apply the stop policy."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "agent" / "main-agent" / "scripts" / "report_round.py"


class _Recorder(HTTPServer):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.records: list[dict] = []


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        self.server.records.append({"path": self.path, "body": body,
                                    "auth": self.headers.get("Authorization")})
        self.send_response(202)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def recorder():
    s = _Recorder(("127.0.0.1", 0), _Handler)
    t = threading.Thread(target=s.serve_forever, daemon=True)
    t.start()
    host, port = s.server_address
    s.base_url = f"http://{host}:{port}"
    try:
        yield s
    finally:
        s.shutdown()
        s.server_close()


def _run(env_extra: dict, argv: list[str]) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({k: str(v) for k, v in env_extra.items()})
    return subprocess.run([sys.executable, str(_SCRIPT), *argv],
                          env=env, capture_output=True, text=True, timeout=10)


def test_posts_round_to_runner(recorder):
    proc = _run(
        {"ALPHA_INTERNAL_RUNNER_URL": recorder.base_url, "ALPHA_INTERNAL_TOKEN": "tok",
         "ALPHA_SESSION_ID": "s_a", "ALPHA_JOB_ID": "j_1"},
        ["--round-index", "2", "--plan-id", "plan_x", "--best-metric", "0.82",
         "--summary", "icm helped"],
    )
    assert proc.returncode == 0, proc.stderr
    assert len(recorder.records) == 1
    rec = recorder.records[0]
    assert rec["path"] == "/internal/loop/round"
    assert rec["auth"] == "Bearer tok"
    b = rec["body"]
    assert b["session_id"] == "s_a" and b["job_id"] == "j_1"
    assert b["round_index"] == 2 and b["plan_id"] == "plan_x"
    assert b["best_metric"] == 0.82 and b["summary"] == "icm helped"


def test_missing_metric_is_allowed(recorder):
    proc = _run(
        {"ALPHA_INTERNAL_RUNNER_URL": recorder.base_url, "ALPHA_INTERNAL_TOKEN": "tok",
         "ALPHA_SESSION_ID": "s_a", "ALPHA_JOB_ID": "j_1"},
        ["--round-index", "1", "--summary", "no numeric result"],
    )
    assert proc.returncode == 0, proc.stderr
    assert recorder.records[0]["body"]["best_metric"] is None


def test_unreachable_runner_does_not_block(recorder):
    # Reporting is best-effort; the runner has a backstop. Never fail the agent over it.
    proc = _run(
        {"ALPHA_INTERNAL_RUNNER_URL": "http://127.0.0.1:1", "ALPHA_INTERNAL_TOKEN": "tok",
         "ALPHA_SESSION_ID": "s_a", "ALPHA_JOB_ID": "j_1"},
        ["--round-index", "1"],
    )
    assert proc.returncode == 0, proc.stderr
