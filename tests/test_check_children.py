"""E2E tests for agent/main-agent/scripts/check_children.py.

Runs the script as a subprocess and stands up a stdlib HTTPServer on
127.0.0.1:0 that answers GET /internal/children/<anything> with a canned list.
No real network beyond loopback, no urllib mocking.
"""

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
_SCRIPT = _REPO_ROOT / "agent" / "main-agent" / "scripts" / "check_children.py"

_CHILDREN = [
    {
        "job_id": "j_1",
        "status": "done",
        "done": True,
        "summary": "Entropy schedule beat baseline by 12%.\nDetails follow...",
        "metrics": {"mean_return": 0.81},
    },
    {
        "job_id": "j_2",
        "status": "running",
        "done": False,
        "summary": None,
        "metrics": {},
    },
]


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/internal/children/"):
            body = json.dumps(_CHILDREN).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):  # silence
        pass


@pytest.fixture
def server_url():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_check_children_prints_status_lines(server_url):
    env = os.environ.copy()
    env.update(
        {
            "ALPHA_INTERNAL_RUNNER_URL": server_url,
            "ALPHA_INTERNAL_TOKEN": "tok",
            "ALPHA_JOB_ID": "j_root",
        }
    )
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    # Done child: tab-separated job_id, status, and the first line of summary.
    assert "j_1\tdone\tEntropy schedule beat baseline by 12%." in lines
    # Running child: summary column is "-".
    assert "j_2\trunning\t-" in lines


def test_check_children_unreachable_runner_exits_1():
    env = os.environ.copy()
    env.update(
        {
            # Port 1 is not bound: connection refused -> clean exit 1.
            "ALPHA_INTERNAL_RUNNER_URL": "http://127.0.0.1:1",
            "ALPHA_INTERNAL_TOKEN": "tok",
            "ALPHA_JOB_ID": "j_root",
        }
    )
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 1
    assert result.stderr.strip() != ""
    # No Python traceback leaked to the user.
    assert "Traceback" not in result.stderr
