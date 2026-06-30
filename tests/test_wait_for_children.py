"""E2E tests for agent/main-agent/scripts/wait_for_children.py.

Runs the script as a subprocess against a stdlib HTTPServer on 127.0.0.1:0 that
answers GET /internal/children/<anything> with a canned list. No real network
beyond loopback, no urllib mocking.

The key invariant: the main agent must NOT block forever on a child the runner
already finalized. A `cancelled` child (orphan reap / parent-terminal, see
runner/loops.py:_cancel_orphans_if_terminal) is terminal and carries NO
RunResult, so `done` is False and only its status marks it finished.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "agent" / "main-agent" / "scripts" / "wait_for_children.py"


def _make_server(children: list[dict]):
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path.startswith("/internal/children/"):
                body = json.dumps(children).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):  # silence
            pass

    return HTTPServer(("127.0.0.1", 0), _Handler)


def _run_wait(server_url: str, job_ids: list[str], timeout: str = "2", poll: str = "0.1"):
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *job_ids, "--timeout", timeout, "--poll-sec", poll],
        capture_output=True,
        text=True,
        env={
            "ALPHA_INTERNAL_RUNNER_URL": server_url,
            "ALPHA_INTERNAL_TOKEN": "tok",
            "ALPHA_JOB_ID": "j_root",
            "PATH": "/usr/bin:/bin",
        },
        timeout=30,
    )


@pytest.fixture
def serve():
    servers: list[HTTPServer] = []
    threads: list[threading.Thread] = []

    def _start(children: list[dict]) -> str:
        server = _make_server(children)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append(server)
        threads.append(thread)
        host, port = server.server_address
        return f"http://{host}:{port}"

    yield _start

    for server in servers:
        server.shutdown()
        server.server_close()
    for thread in threads:
        thread.join(timeout=5)


def test_cancelled_child_is_terminal(serve):
    """A cancelled child (no RunResult, done=False) must end the wait, not hang it."""
    url = serve([{"job_id": "j_1", "status": "cancelled", "done": False, "summary": None}])
    result = _run_wait(url, ["j_1"])
    assert result.returncode == 0, (
        f"cancelled child should be terminal; got {result.returncode} / {result.stderr}"
    )


def test_done_and_failed_and_cancelled_mix_all_terminal(serve):
    url = serve([
        {"job_id": "j_1", "status": "done", "done": True, "summary": "ok"},
        {"job_id": "j_2", "status": "failed", "done": True, "summary": "boom"},
        {"job_id": "j_3", "status": "cancelled", "done": False, "summary": None},
    ])
    result = _run_wait(url, ["j_1", "j_2", "j_3"])
    assert result.returncode == 0, result.stderr


def test_running_child_times_out(serve):
    """Sanity: a still-running child keeps the wait blocking until timeout (exit 2)."""
    url = serve([{"job_id": "j_1", "status": "running", "done": False, "summary": None}])
    result = _run_wait(url, ["j_1"], timeout="1")
    assert result.returncode == 2
    assert "j_1" in result.stderr
