"""The sub-agent launcher must stream its claude child's console to the bus.

Today it ``os.execvp``s claude, so the sub-agent's stdout/stderr inherit to the
Modal log and "die" there — invisible to the per-subagent console view. The
launcher now spawns claude and relays BOTH pipes as `console` events tagged with
this sub-agent's session/job/depth. Pure: fake Popen + fake relay, no Modal.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

# Both agent dirs ship a `launch.py`; load the sub-agent's under a distinct module
# name so it can't collide with the main-agent's `launch` in sys.modules.
_SUB = Path(__file__).resolve().parents[1] / "agent" / "sub-agent"
sys.path.insert(0, str(_SUB))
sys.path.insert(0, str(_SUB / ".claude" / "hooks"))
_spec = importlib.util.spec_from_file_location("sub_launch", _SUB / "launch.py")
sublaunch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sublaunch)


def test_sub_main_requires_a_job_id(monkeypatch):
    monkeypatch.delenv("ALPHA_JOB_ID", raising=False)
    with pytest.raises(SystemExit):
        sublaunch.main()


def test_sub_main_relays_both_pipes_as_console_tagged_to_this_subagent(monkeypatch):
    class FakeProc:
        def __init__(self):
            self.stdout = io.StringIO("train step 1\n")
            self.stderr = io.StringIO("warn: slow\n")

        def wait(self):
            return 0

    captured: dict = {}

    def fake_popen(*a, **k):
        captured.update(k)
        return FakeProc()

    recorded: list[tuple[list[str], dict]] = []

    def fake_console(lines, _emit, **kw):
        recorded.append((list(lines), kw))

    monkeypatch.setattr(sublaunch.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sublaunch, "relay_console", fake_console)
    monkeypatch.setenv("ALPHA_JOB_ID", "j_c")
    monkeypatch.setenv("ALPHA_SESSION_ID", "s1")
    monkeypatch.setenv("ALPHA_DEPTH", "1")

    with pytest.raises(SystemExit) as ei:
        sublaunch.main()

    assert ei.value.code == 0
    # Both pipes captured (not inherited to the Modal log).
    assert captured.get("stdout") is sublaunch.subprocess.PIPE
    assert captured.get("stderr") is sublaunch.subprocess.PIPE
    # Both relayed as console, one stdout + one stderr stream.
    assert sorted(kw["stream"] for _, kw in recorded) == ["stderr", "stdout"]
    # Tagged to this sub-agent so the frontend can route to its own console.
    for _lines, kw in recorded:
        assert kw["session_id"] == "s1"
        assert kw["job_id"] == "j_c"
        assert kw["depth"] == 1
