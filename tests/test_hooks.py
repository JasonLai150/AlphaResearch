"""Tests for Claude Code agent telemetry hooks (Task 4).

The hooks under test are stdlib-only scripts that:
  - POST telemetry to a runner over HTTP (PostToolUse / UserPromptSubmit / Stop)
  - (sub-agent Stop) atomically write a RunResult into a shared volume

These tests spin up a stdlib HTTP recorder on 127.0.0.1:0 in a daemon thread,
then run each hook as a subprocess feeding it a JSON event on stdin, and assert
on what got POSTed (and, for finalize, what got written to disk).
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

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_HOOKS = REPO_ROOT / "agent" / "main-agent" / ".claude" / "hooks"
SUB_HOOKS = REPO_ROOT / "agent" / "sub-agent" / ".claude" / "hooks"

TOKEN = "tok"


class _Recorder(HTTPServer):
    """HTTPServer that accumulates received POSTs for assertions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records: list[dict] = []
        self.lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {"_raw": raw.decode("utf-8", "replace")}
        rec = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "body": body,
        }
        with self.server.lock:  # type: ignore[attr-defined]
            self.server.records.append(rec)  # type: ignore[attr-defined]
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):  # silence stderr access logs
        pass


@pytest.fixture()
def recorder():
    server = _Recorder(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    server.base_url = f"http://{host}:{port}"  # type: ignore[attr-defined]
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _base_env(runner_url: str, **overrides) -> dict:
    env = dict(os.environ)
    env.update(
        {
            "ALPHA_INTERNAL_RUNNER_URL": runner_url,
            "ALPHA_INTERNAL_TOKEN": TOKEN,
            "ALPHA_SESSION_ID": "s_1",
            "ALPHA_JOB_ID": "j_1",
        }
    )
    env.update({k: str(v) for k, v in overrides.items()})
    return env


def _run_hook(hook: Path, stdin: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(hook)],
        input=stdin,
        env=env,
        capture_output=True,
        text=True,
        timeout=8,
    )


def test_main_agent_stream_event_posts(recorder):
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "ls -la"},
            "tool_response": "drwxr-xr-x ...",
        }
    )
    proc = _run_hook(
        MAIN_HOOKS / "stream_event.py",
        payload,
        _base_env(recorder.base_url, ALPHA_DEPTH="0"),
    )
    assert proc.returncode == 0, proc.stderr

    assert len(recorder.records) == 1, recorder.records
    rec = recorder.records[0]
    assert rec["path"] == "/internal/events"
    assert rec["authorization"] == f"Bearer {TOKEN}"
    body = rec["body"]
    assert body["session_id"] == "s_1"
    assert body["job_id"] == "j_1"
    assert body["depth"] == 0
    assert body["type"] == "log"
    assert "Bash" in body["payload"]["tool"]


def test_sub_agent_stream_event_tags_depth(recorder):
    payload = json.dumps(
        {"tool_name": "Read", "tool_input": {"file_path": "/x"}, "tool_response": "ok"}
    )
    proc = _run_hook(
        SUB_HOOKS / "stream_event.py",
        payload,
        _base_env(recorder.base_url, ALPHA_DEPTH="1"),
    )
    assert proc.returncode == 0, proc.stderr

    assert len(recorder.records) == 1, recorder.records
    body = recorder.records[0]["body"]
    assert body["depth"] == 1


def test_log_transcript_posts(recorder):
    payload = json.dumps({"prompt": "hello"})
    proc = _run_hook(
        MAIN_HOOKS / "log_transcript.py",
        payload,
        _base_env(recorder.base_url),
    )
    assert proc.returncode == 0, proc.stderr

    assert len(recorder.records) == 1, recorder.records
    rec = recorder.records[0]
    assert rec["path"] == "/internal/transcript"
    body = rec["body"]
    assert body["role"] == "user"
    assert body["content"] == "hello"


def test_sub_finalize_writes_atomic_result(recorder, tmp_path):
    """SEV-7: finalize copies the agent's own result.json (per sub-agent CLAUDE.md)
    into the volume atomically + a .done sentinel."""
    ws = tmp_path / "workspace"
    dispatch = tmp_path / "dispatched"
    ws.mkdir()
    (ws / "result.json").write_text(json.dumps({
        "job_id": "j_c", "idea_id": "idea_1", "status": "done",
        "summary": "ppo+icm hit 0.82", "metrics": {"score": 0.82}, "validated": True,
    }))

    env = _base_env(
        recorder.base_url,
        ALPHA_DEPTH="1",
        ALPHA_JOB_ID="j_c",
        ALPHA_WORKSPACE=str(ws),
        ALPHA_DISPATCH_DIR=str(dispatch),
    )
    proc = _run_hook(SUB_HOOKS / "finalize.py", "", env)
    assert proc.returncode == 0, proc.stderr

    result_path = dispatch / "j_c.result.json"
    done_path = dispatch / "j_c.result.json.done"
    tmp_leftover = dispatch / "j_c.result.json.tmp"

    assert result_path.exists(), "result.json not written"
    assert done_path.exists(), "sentinel .done not written"
    assert not tmp_leftover.exists(), "leftover .tmp not cleaned up"

    result = json.loads(result_path.read_text())
    assert result["job_id"] == "j_c"
    assert result["status"] == "done"
    assert result["summary"] == "ppo+icm hit 0.82"
    assert result["metrics"] == {"score": 0.82}

    # The summary event must have been pushed to the runner.
    events = [r for r in recorder.records if r["path"] == "/internal/events"]
    assert len(events) == 1, recorder.records
    assert events[0]["body"]["type"] == "summary"
    assert events[0]["body"]["payload"]["finished"] is True


def test_sub_finalize_missing_result_marks_failed(recorder, tmp_path):
    """SEV-7: no result.json -> a 'failed' result is still published (+ sentinel)."""
    ws = tmp_path / "workspace"
    dispatch = tmp_path / "dispatched"
    ws.mkdir()
    env = _base_env(
        recorder.base_url, ALPHA_DEPTH="1", ALPHA_JOB_ID="j_c",
        ALPHA_WORKSPACE=str(ws), ALPHA_DISPATCH_DIR=str(dispatch),
    )
    proc = _run_hook(SUB_HOOKS / "finalize.py", "", env)
    assert proc.returncode == 0, proc.stderr
    result = json.loads((dispatch / "j_c.result.json").read_text())
    assert result["status"] == "failed"
    assert (dispatch / "j_c.result.json.done").exists()


def test_hook_swallows_unreachable_runner():
    # Port 1 is privileged/closed -> connection refused fast.
    payload = json.dumps(
        {"tool_name": "Bash", "tool_input": {}, "tool_response": "x"}
    )
    env = _base_env("http://127.0.0.1:1", ALPHA_DEPTH="0")
    proc = _run_hook(MAIN_HOOKS / "stream_event.py", payload, env)
    assert proc.returncode == 0, (
        f"hook must exit 0 even when runner unreachable; got {proc.returncode}\n"
        f"stderr: {proc.stderr}"
    )
