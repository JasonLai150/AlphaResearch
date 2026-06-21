"""E2E tests for agent/main-agent/scripts/dispatch_subagent.py.

These run the script as a real subprocess (under `uv run python`) and stand up a
tiny stdlib HTTPServer recorder on 127.0.0.1:0 in a daemon thread to capture the
runner-bound POST. No real network, no urllib mocking.
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
_SCRIPT = _REPO_ROOT / "agent" / "main-agent" / "scripts" / "dispatch_subagent.py"


def _valid_plan() -> dict:
    """A minimal ResearchPlan that passes schema + diversity validation.

    3 ideas, all distinct titles, tags spread across 3 axes (cap = ceil(3/2)=2).
    Each idea has an explicit id so the test can target one with --idea-id.
    """
    return {
        "id": "plan_test01",
        "goal": "Improve sample efficiency on DoorKey.",
        "env_id": "MiniGrid-DoorKey-8x8",
        "reward_fn_spec": "Sparse +1 on reaching the goal, 0 otherwise. Frozen.",
        "base_hparams": {"lr": 3e-4, "gamma": 0.99, "n_steps": 128},
        "target_metric": "mean_return_at_500k_steps",
        "budget_steps": 500000,
        "ideas": [
            {
                "id": "idea_alpha",
                "title": "entropy-bonus-schedule",
                "diversity_tag": "exploration",
                "hypothesis": "Higher early entropy speeds discovery of the key.",
                "approach": "Linearly decay entropy coef from 0.05 to 0.0.",
                "success_criterion": "Reaches goal 20% sooner than baseline.",
            },
            {
                "id": "idea_beta",
                "title": "potential-based-shaping",
                "diversity_tag": "reward_shaping",
                "hypothesis": "Distance-to-key shaping densifies the signal.",
                "approach": "Add potential-based shaping on manhattan distance.",
                "success_criterion": "Higher mean return at 500k steps.",
            },
            {
                "id": "idea_gamma",
                "title": "recurrent-encoder",
                "diversity_tag": "architecture",
                "hypothesis": "Recurrence helps with partial observability.",
                "approach": "Swap the MLP head for a GRU.",
                "success_criterion": "Higher final return than baseline MLP.",
            },
        ],
    }


class _Recorder(HTTPServer):
    """HTTPServer that stashes the most recent POST it received."""

    last_path: str | None = None
    last_headers: dict | None = None
    last_body: bytes | None = None
    post_count: int = 0


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        self.server.last_path = self.path
        self.server.last_headers = dict(self.headers)
        self.server.last_body = body
        self.server.post_count += 1
        self.send_response(202)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"queued": true}')

    def log_message(self, *args):  # silence test output
        pass


@pytest.fixture
def recorder():
    server = _Recorder(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    try:
        yield server, base_url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _write_plan(tmp_path: Path) -> Path:
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(_valid_plan()))
    return plan_path


def _run(plan_path: Path, out_dir: Path, env: dict) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    full_env.update(env)
    return subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--plan",
            str(plan_path),
            "--idea-id",
            "idea_beta",
            "--out-dir",
            str(out_dir),
            "--parent-job-id",
            "j_root",
        ],
        capture_output=True,
        text=True,
        env=full_env,
    )


def test_dispatch_posts_to_runner(recorder, tmp_path):
    server, base_url = recorder
    plan_path = _write_plan(tmp_path)
    out_dir = tmp_path / "dispatched"

    result = _run(
        plan_path,
        out_dir,
        {
            "ALPHA_INTERNAL_RUNNER_URL": base_url,
            "ALPHA_INTERNAL_TOKEN": "tok",
            "ALPHA_SESSION_ID": "s_x",
            "ALPHA_DEPTH": "0",
        },
    )

    assert result.returncode == 0, result.stderr

    # Exactly one POST to the dispatch endpoint, with the right auth header.
    assert server.post_count == 1
    assert server.last_path == "/internal/dispatch"
    assert server.last_headers is not None
    assert server.last_headers.get("Authorization") == "Bearer tok"

    posted = json.loads(server.last_body.decode("utf-8"))
    assert posted["session_id"] == "s_x"
    assert posted["depth"] == 1
    assert posted["parent_job_id"] == "j_root"
    assert posted["kind"] == "agent"
    assert "plan" in posted
    assert posted["idea_id"] == "idea_beta"

    # Local audit file exists, named after the generated job_id.
    stdout = json.loads(result.stdout.strip().splitlines()[-1])
    job_id = stdout["job_id"]
    assert (out_dir / f"{job_id}.json").exists()


def test_parent_job_id_defaults_to_alpha_job_id(recorder, tmp_path):
    """Regression: with NO --parent-job-id (the real main-agent invocation), the
    parent must default to $ALPHA_JOB_ID — the runner-injected root id — not the
    literal 'root' (which would 404 at /internal/dispatch)."""
    server, base_url = recorder
    plan_path = _write_plan(tmp_path)
    out_dir = tmp_path / "dispatched"
    env = os.environ.copy()
    env.update({
        "ALPHA_INTERNAL_RUNNER_URL": base_url,
        "ALPHA_INTERNAL_TOKEN": "tok",
        "ALPHA_SESSION_ID": "s_x",
        "ALPHA_JOB_ID": "j_realroot",
        "ALPHA_DEPTH": "0",
    })
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--plan", str(plan_path),
         "--idea-id", "idea_beta", "--out-dir", str(out_dir)],  # NO --parent-job-id
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    posted = json.loads(server.last_body.decode("utf-8"))
    assert posted["parent_job_id"] == "j_realroot"


def test_dispatch_local_only_no_post(tmp_path):
    """With ALPHA_INTERNAL_RUNNER_URL unset, the script still succeeds and writes
    the audit file, but performs no HTTP push."""
    plan_path = _write_plan(tmp_path)
    out_dir = tmp_path / "dispatched"

    env = os.environ.copy()
    env.pop("ALPHA_INTERNAL_RUNNER_URL", None)
    env["ALPHA_SESSION_ID"] = "s_local"
    env["ALPHA_DEPTH"] = "0"

    result = subprocess.run(
        [
            sys.executable,
            str(_SCRIPT),
            "--plan",
            str(plan_path),
            "--idea-id",
            "idea_beta",
            "--out-dir",
            str(out_dir),
            "--parent-job-id",
            "j_root",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    stdout = json.loads(result.stdout.strip().splitlines()[-1])
    job_id = stdout["job_id"]
    assert (out_dir / f"{job_id}.json").exists()
