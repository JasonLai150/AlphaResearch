"""console_relay turns a child process's raw stdout/stderr lines into `console`
events for the runner bus — the operational console that today only reaches the
Cloud Run / Modal logs and "dies" there. Pure + stdlib-only: feed canned lines
and a fake emit, assert the event sequence. No subprocess, no claude binary.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent" / "main-agent"))
from console_relay import relay_console  # noqa: E402


def _run(lines, **kw):
    calls: list[tuple[str, dict]] = []
    relay_console(
        lines,
        lambda path, body: calls.append((path, body)),
        session_id="s1",
        job_id="j1",
        depth=0,
        **kw,
    )
    return calls


def test_each_nonblank_line_becomes_a_console_event():
    calls = _run(["boot\n", "training step 1\n"])
    assert [p for p, _ in calls] == ["/internal/events", "/internal/events"]
    bodies = [b for _, b in calls]
    assert all(b["type"] == "console" for b in bodies)
    assert [b["payload"]["line"] for b in bodies] == ["boot", "training step 1"]
    assert all(b["payload"]["stream"] == "stderr" for b in bodies)  # default channel
    assert all(
        b["session_id"] == "s1" and b["job_id"] == "j1" and b["depth"] == 0
        for b in bodies
    )


def test_blank_lines_emit_nothing():
    assert _run(["", "   ", "\n"]) == []


def test_stream_label_is_configurable():
    calls = _run(["hi"], stream="stdout")
    assert calls[0][1]["payload"]["stream"] == "stdout"


def test_long_lines_are_truncated():
    calls = _run(["x" * 5000], max_line=100)
    assert len(calls[0][1]["payload"]["line"]) == 100


def test_depth_is_forwarded_for_per_subagent_routing():
    calls: list[tuple[str, dict]] = []
    relay_console(["deep"], lambda p, b: calls.append((p, b)),
                  session_id="s1", job_id="j_c", depth=2)
    assert calls[0][1]["depth"] == 2 and calls[0][1]["job_id"] == "j_c"


def test_tee_mirrors_every_raw_line_including_blanks():
    # The tee keeps the operational log intact (Cloud Run / Modal logs still get
    # every byte) while only non-blank lines stream to the bus.
    sink = io.StringIO()
    _run(["a\n", "\n", "b"], tee=sink)
    assert sink.getvalue() == "a\n\nb\n"


def test_a_failing_emit_never_stops_the_tee_or_the_loop():
    # Telemetry is best-effort: one bad emit must not lose later console lines or
    # the operational mirror (a crashed relay would blind the ops logs too).
    sink = io.StringIO()
    seen: list[str] = []

    def flaky(_path, body):
        seen.append(body["payload"]["line"])
        if body["payload"]["line"] == "one":
            raise RuntimeError("bus down")

    relay_console(["one\n", "two\n"], flaky,
                  session_id="s1", job_id="j1", depth=0, tee=sink)
    assert seen == ["one", "two"]          # kept going after the failure
    assert sink.getvalue() == "one\ntwo\n"  # ops mirror intact


def test_sender_delivers_every_line_to_push_in_order_when_push_is_fast():
    from console_relay import make_console_sender

    got: list[int] = []
    s = make_console_sender(lambda _p, b: got.append(b["n"]))
    for n in range(5):
        s.emit("/x", {"n": n})
    s.close()  # drains then joins
    assert got == [0, 1, 2, 3, 4]


def test_sender_emit_never_blocks_and_drops_oldest_when_push_is_stuck():
    # The whole point: the network must not back-pressure the pipe drain. With a
    # wedged push, emit must stay non-blocking and the bounded queue drop, rather
    # than block the relay thread (which would fill the OS pipe and stall claude).
    import threading
    import time

    from console_relay import make_console_sender

    gate = threading.Event()
    got: list[int] = []

    def stuck_push(_path, body):
        got.append(body["n"])
        if body["n"] == 0:
            gate.wait(2.0)  # wedge the worker on the first item

    s = make_console_sender(stuck_push, maxlen=2)
    s.emit("/x", {"n": 0})
    time.sleep(0.1)  # let the worker pull n=0 and block
    # Worker is stuck; the bounded queue (max 2) now absorbs/drops the rest.
    for n in range(1, 8):
        s.emit("/x", {"n": n})  # MUST NOT block or raise
    gate.set()
    s.close()

    assert got[0] == 0          # first delivered
    assert 7 in got             # newest survived the drop-oldest
    assert len(got) < 8         # some lines were dropped, not all 8 delivered


def test_main_and_sub_agent_console_relay_are_identical():
    # Separate Docker images can't share a module, so each agent dir carries its
    # own copy (like _push.py). Guard against drift: they must stay byte-identical.
    root = Path(__file__).resolve().parents[1] / "agent"
    main = (root / "main-agent" / "console_relay.py").read_text()
    sub = (root / "sub-agent" / "console_relay.py").read_text()
    assert main == sub


def test_console_is_a_valid_event_type_end_to_end():
    # The agent posts type="console"; the internal API model must accept it or
    # every console POST 422s before it can reach Redis/SSE.
    from infra.schemas import EventType
    from runner.internal_api import EventIn

    ev = EventIn(session_id="s1", job_id="j1", type="console",
                 payload={"stream": "stderr", "line": "x"})
    assert ev.type == EventType.console
