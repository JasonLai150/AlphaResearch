"""launch._build_argv must invoke claude in streaming print mode so the relay
can tail assistant text. Pure argv assertion — no subprocess, no claude binary.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent" / "main-agent"))
import launch  # noqa: E402


def test_build_argv_uses_streaming_print_mode():
    argv = launch._build_argv("do the thing", "claude-sonnet-4-6")
    assert argv[0] == "claude"
    # Print mode with the prompt, the model, and streaming JSON deltas.
    assert argv[argv.index("-p") + 1] == "do the thing"
    assert argv[argv.index("--model") + 1] == "claude-sonnet-4-6"
    assert "--output-format" in argv
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in argv            # required with -p + stream-json
    assert "--include-partial-messages" in argv  # token-level deltas
    assert "--dangerously-skip-permissions" in argv


def test_main_forwards_exit_code_when_relay_raises(monkeypatch):
    # If relay blows up mid-stream, the launcher must still exit with claude's
    # return code (the Cloud Run Job success/failure signal), not a traceback.
    class FakeProc:
        def __init__(self):
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")
        def wait(self):
            return 7

    monkeypatch.setattr(launch, "_bootstrap", lambda url, tok: {"goal": "g", "mode": "oneshot"})
    monkeypatch.setattr(launch.subprocess, "Popen", lambda *a, **k: FakeProc())
    def _boom(*a, **k):
        raise RuntimeError("pipe broke")
    monkeypatch.setattr(launch, "relay", _boom)
    monkeypatch.setenv("ALPHA_INTERNAL_RUNNER_URL", "http://runner.test")
    monkeypatch.setenv("ALPHA_INTERNAL_TOKEN", "tok")

    with pytest.raises(SystemExit) as ei:
        launch.main()
    assert ei.value.code == 7


def test_main_captures_and_relays_claude_stderr(monkeypatch):
    # claude's stderr is the operational console; today it inherits straight to
    # the Cloud Run log and "dies" there. The launcher must PIPE it and relay
    # every line to the bus (tagged stderr) so it reaches the frontend console.
    class FakeProc:
        def __init__(self):
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("boot diag\nready\n")
        def wait(self):
            return 0

    captured_kwargs: dict = {}

    def fake_popen(*a, **k):
        captured_kwargs.update(k)
        return FakeProc()

    recorded: list[tuple[list[str], dict]] = []

    def fake_console(lines, _emit, **kw):
        recorded.append((list(lines), kw))

    monkeypatch.setattr(launch, "_bootstrap", lambda url, tok: {"goal": "g", "mode": "oneshot"})
    monkeypatch.setattr(launch.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(launch, "relay", lambda *a, **k: None)   # ignore the stdout path
    monkeypatch.setattr(launch, "relay_console", fake_console)
    monkeypatch.setenv("ALPHA_INTERNAL_RUNNER_URL", "http://runner.test")
    monkeypatch.setenv("ALPHA_INTERNAL_TOKEN", "tok")

    with pytest.raises(SystemExit) as ei:
        launch.main()

    assert ei.value.code == 0
    # stderr was piped (not inherited).
    assert captured_kwargs.get("stderr") is launch.subprocess.PIPE
    # ...and relayed as a stderr console stream, one relay over the stderr pipe.
    assert len(recorded) == 1
    lines, kw = recorded[0]
    assert lines == ["boot diag\n", "ready\n"]
    assert kw["stream"] == "stderr"
    assert kw["session_id"] == "" and kw["depth"] == 0  # env-derived, unset here
