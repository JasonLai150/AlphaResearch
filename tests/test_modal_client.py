"""Volume path conventions + dispatch-record I/O (Task 2). No Modal SDK calls —
the spawn/poll lifecycle is exercised (mocked) in test_runner_loops.py."""

from __future__ import annotations

import json
from pathlib import Path

from infra.config import settings
from runner import modal_client


def test_volume_name():
    assert modal_client.session_volume_name("s_abc") == "alpha-session-s_abc"


def test_local_volume_path():
    assert modal_client.local_volume_path("s_x") == Path(settings.volume_root) / "s_x"


def test_dispatch_dir_and_results():
    d = modal_client.dispatch_dir("s_x")
    assert d == Path(settings.volume_root) / "s_x" / ".dispatched"
    r, f = modal_client.results_for("s_x", "j_1")
    assert r == d / "j_1.result.json"
    assert f == d / "j_1.failed.json"
    assert modal_client.artifacts_dir("s_x", "j_1") == d / "artifacts" / "j_1"
    assert modal_client.result_done_sentinel("s_x", "j_1") == d / "j_1.result.json.done"


def test_write_dispatch_record_roundtrips():
    rec = {"job_id": "j_1", "parent_job_id": "j_root", "session_id": "s_x", "depth": 1}
    path = modal_client.write_dispatch_record("s_x", "j_1", rec)
    assert path == modal_client.dispatch_dir("s_x") / "j_1.json"
    assert json.loads(path.read_text())["job_id"] == "j_1"
