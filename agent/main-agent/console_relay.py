#!/usr/bin/env python3
"""Relay a child process's raw stdout/stderr into runner telemetry as `console`
events — the operational console (Claude Code's diagnostics, tracebacks, trainer
logs) that otherwise only lands in Cloud Run / Modal logs and "dies" there.

Each non-blank line becomes one `console` event tagged with this agent's
session/job/depth, so the frontend can route it to a per-agent console view.
A ``tee`` (default: the real stderr at the call site) still receives every raw
line verbatim, so the ops logs are preserved, not replaced.

Pure + stdlib-only by design (``relay_console`` takes an injected ``emit`` and a
``tee`` stream) so it unit-tests without a network or the claude binary. The
agent image excludes ``infra/`` — do NOT import from it here. Mirrors stream_relay.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, Iterable
from typing import TextIO

Emit = Callable[[str, dict], None]

_MAX_LINE = 2000  # cap a single console line so one runaway line can't bloat Redis
_QUEUE_MAX = 2000  # bounded buffer between the pipe drain and the network sender


class _ConsoleSender:
    """A non-blocking, bounded, drop-oldest bridge from the console relay to the
    blocking HTTP ``push``. CRITICAL: the relay thread drains the child's pipe, so
    it must never block on the network — if it did, the OS pipe buffer would fill
    and the child (claude / the trainer) would stall on write(). So ``emit`` only
    enqueues (dropping the oldest line when the buffer is full, since console is
    best-effort telemetry and the tee already preserved every line to the ops log),
    and a single worker thread does the actual blocking ``push``."""

    def __init__(self, push: Emit, *, maxlen: int = _QUEUE_MAX, drain_timeout: float = 10.0):
        self._push = push
        self._q: queue.Queue = queue.Queue(maxsize=maxlen)
        self._drain_timeout = drain_timeout
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def emit(self, path: str, body: dict) -> None:
        try:
            self._q.put_nowait((path, body))
        except queue.Full:
            try:  # drop the oldest queued line to make room for the newest
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait((path, body))
            except queue.Full:
                pass  # still full (rare race) — drop this line; ops log still has it

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:  # sentinel from close()
                return
            path, body = item
            try:
                self._push(path, body)
            except Exception:  # noqa: BLE001 — telemetry is best-effort, never fatal
                pass

    def close(self) -> None:
        """Signal the worker to drain remaining lines then stop; bounded join so a
        dead runner can't hang shutdown."""
        self._q.put(None)
        self._worker.join(timeout=self._drain_timeout)


def make_console_sender(push: Emit, *, maxlen: int = _QUEUE_MAX) -> _ConsoleSender:
    """Build a non-blocking sender over a blocking ``push``. Use ``sender.emit`` as
    the ``emit`` for relay_console, and call ``sender.close()`` when the child exits."""
    return _ConsoleSender(push, maxlen=maxlen)


def relay_console(
    lines: Iterable[str],
    emit: Emit,
    *,
    session_id: str,
    job_id: str,
    depth: int = 0,
    stream: str = "stderr",
    tee: TextIO | None = None,
    max_line: int = _MAX_LINE,
) -> None:
    """Stream ``lines`` (an open pipe or any iterable) to the bus as `console`
    events. ``stream`` labels the channel ("stderr"/"stdout"). Best-effort: a
    failing ``emit`` is swallowed so one telemetry hiccup never drops later lines
    or the ops mirror."""
    for line in lines:
        if tee is not None:
            tee.write(line if line.endswith("\n") else line + "\n")
            tee.flush()
        text = line.rstrip("\n")
        if not text.strip():
            continue
        if len(text) > max_line:
            text = text[:max_line]
        try:
            emit(
                "/internal/events",
                {
                    "session_id": session_id,
                    "job_id": job_id,
                    "depth": depth,
                    "type": "console",
                    "payload": {"stream": stream, "line": text},
                },
            )
        except Exception:  # noqa: BLE001 — telemetry is best-effort, never fatal
            pass
