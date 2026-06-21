"""SSE resume / Last-Event-ID logic — PURE unit tests (no Redis, fake or real).

The SSE reconnect contract spans two pure pieces:

1. ``orchestrator.api.stream`` turns the incoming ``Last-Event-ID`` header into the
   ``start`` cursor it hands to the tailer: a missing header replays from the very
   beginning (``"0"``), a real id resumes *after* it. We assert this by stubbing
   ``store.tail_events`` to capture the cursor it was called with — no Redis.
2. ``infra.store.tail_events`` feeds that cursor straight into Redis ``XREAD``,
   whose ``{stream: id}`` form returns entries STRICTLY AFTER ``id`` (exclusive).
   So "resume after the Last-Event-ID" == "XREAD with last_id == that id". We stub
   ``store.get_redis()`` with a tiny recorder and assert the exact id XREAD is asked
   for, plus that the tailer advances the cursor past each yielded entry (so a
   re-XREAD never replays what it already delivered).
3. ``infra.store._normalize_last_id`` is the pure guard that maps a malformed /
   hostile Last-Event-ID to "only new events" (``"$"``) while passing real ids,
   the full-replay sentinel ``"0"``, and the Redis range sentinels through.

All three are exercised at the function level with monkeypatched stubs — there is
no Redis dependency, matching tests/test_public_auth.py's stub style.
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

import infra.store as store
import orchestrator.api as api
from infra.schemas import EventEnvelope, EventType

# pytest-asyncio runs in Mode.AUTO (see pyproject), so async tests are detected
# automatically — no module-level asyncio mark needed (it would also wrongly tag
# the sync _normalize_last_id param tests).


# --- 1. API endpoint: Last-Event-ID header -> tailer start cursor ----------

class _CaptureTail:
    """Stub for store.tail_events that records the start cursor and yields nothing."""

    def __init__(self) -> None:
        self.start: str | None = None

    def __call__(self, sid: str, start: str):
        self.start = start

        async def _empty():
            return
            yield  # pragma: no cover  (makes this an async generator)

        return _empty()


async def _drain_stream_response(resp):
    """Pull every chunk out of an EventSourceResponse's body iterator."""
    out = []
    async for chunk in resp.body_iterator:
        out.append(chunk)
    return out


def _fake_request():
    class _Req:
        async def is_disconnected(self) -> bool:
            return False

    return _Req()


async def test_endpoint_no_last_event_id_replays_from_start(monkeypatch):
    cap = _CaptureTail()
    monkeypatch.setattr(store, "tail_events", cap)

    resp = await api.stream("s_1", _fake_request(), last_event_id=None, _uid=None)
    await _drain_stream_response(resp)

    # First connect: no header -> replay from the very beginning so the UI never
    # misses events.
    assert cap.start == "0"


async def test_endpoint_resumes_after_given_last_event_id(monkeypatch):
    cap = _CaptureTail()
    monkeypatch.setattr(store, "tail_events", cap)

    resp = await api.stream(
        "s_1", _fake_request(), last_event_id="1700000000000-0", _uid=None
    )
    await _drain_stream_response(resp)

    # Reconnect: the real id is passed straight through as the resume cursor (NOT
    # reset to "0"), so the tailer resumes from exactly there rather than replaying.
    assert cap.start == "1700000000000-0"


# --- 2. tail_events: cursor -> XREAD requests events strictly AFTER it ------

class _RecorderRedis:
    """Minimal async stub of the redis client tail_events touches: records every
    id XREAD is asked for, then serves a fixed batch once and blocks forever after
    (so the tailer drains exactly one page and we can stop)."""

    def __init__(self, stream: str, entries: list[tuple[str, dict]]):
        self._stream = stream
        self._entries = entries
        self.requested_ids: list[str] = []
        self._served = False

    async def xread(self, streams: dict, block: int, count: int):
        # tail_events calls xread({stream: last_id}, ...) — capture the cursor FIRST
        # so the request is recorded even if the poll is cancelled mid-block.
        (_stream, last_id), = streams.items()
        self.requested_ids.append(last_id)
        # Real redis xread(block=...) suspends; yield to the loop so the tailer's
        # poll loop never starves the event loop (and stays cancellable).
        await asyncio.sleep(0)
        if self._served:
            # Emulate a block-timeout (empty) so the consumer loops again.
            return None
        self._served = True
        return [(self._stream, self._entries)]


def _envelope(sid: str) -> EventEnvelope:
    return EventEnvelope(session_id=sid, job_id="j_1", type=EventType.log, payload={})


async def test_tail_events_requests_strictly_after_given_id(monkeypatch):
    sid = "s_1"
    stream_key = store._events_key(sid)
    env = _envelope(sid)
    rec = _RecorderRedis(stream_key, [("1700000000000-5", {"data": env.model_dump_json()})])
    monkeypatch.setattr(store, "get_redis", lambda: rec)

    given = "1700000000000-0"
    out = []
    async for entry_id, _env in store.tail_events(sid, given):
        out.append(entry_id)
        break  # one event is enough to prove the resume cursor

    # XREAD's {stream: id} form is EXCLUSIVE: passing the Last-Event-ID itself makes
    # Redis return only entries AFTER it — i.e. no replay of the already-seen id.
    assert rec.requested_ids[0] == given
    assert out == ["1700000000000-5"]


async def test_tail_events_advances_cursor_past_yielded_entry(monkeypatch):
    sid = "s_1"
    stream_key = store._events_key(sid)
    env = _envelope(sid)
    delivered_id = "1700000000000-5"
    rec = _RecorderRedis(stream_key, [(delivered_id, {"data": env.model_dump_json()})])
    monkeypatch.setattr(store, "get_redis", lambda: rec)

    agen = store.tail_events(sid, "0")
    first_id, _env = await agen.__anext__()
    assert first_id == delivered_id
    # First request used the start cursor "0".
    assert rec.requested_ids[0] == "0"

    # Drive the tailer once more to force the NEXT xread (which the stub answers with
    # a block-timeout), then stop. We must not wait for a second YIELD — there is no
    # second entry — only for the second REQUEST to be recorded.
    nxt = asyncio.ensure_future(agen.__anext__())
    for _ in range(10):
        await asyncio.sleep(0)
        if len(rec.requested_ids) >= 2:
            break
    nxt.cancel()
    with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
        await nxt
    await agen.aclose()

    # The SECOND request must use the id we just delivered, never "0" again —
    # otherwise a reconnect/continuation would replay already-seen events.
    assert rec.requested_ids[1] == delivered_id


async def test_tail_events_no_id_defaults_to_only_new(monkeypatch):
    sid = "s_1"
    stream_key = store._events_key(sid)
    rec = _RecorderRedis(stream_key, [])  # serve an empty page, then block/None
    monkeypatch.setattr(store, "get_redis", lambda: rec)

    agen = store.tail_events(sid)  # default last_id
    # Pull one (empty -> None -> loops) then cancel; we only need the first request.
    task = asyncio.ensure_future(agen.__anext__())
    for _ in range(10):
        await asyncio.sleep(0)  # let the coroutine reach its first xread
        if rec.requested_ids:
            break
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
        await task
    await agen.aclose()

    # No explicit Last-Event-ID at the store layer => "$" (only events arriving now),
    # the normalize default.
    assert rec.requested_ids and rec.requested_ids[0] == "$"


# --- 3. _normalize_last_id: pure ID parsing / normalization guard ----------

@pytest.mark.parametrize(
    "raw",
    [
        "$",                  # only-new sentinel
        "0",                  # full-replay-from-start sentinel
        "+",                  # XRANGE upper sentinel
        "-",                  # XRANGE lower sentinel
        "1700000000000",      # bare ms
        "1700000000000-0",    # ms-seq
        "1700000000000-42",   # ms-seq
        "1700000000000-*",    # ms-autoseq
    ],
)
def test_normalize_passes_valid_ids_through(raw):
    assert store._normalize_last_id(raw) == raw


@pytest.mark.parametrize(
    "raw",
    [
        "",                       # empty
        "not-an-id",              # garbage
        "1700000000000-0-0",      # too many segments
        "abc-1",                  # non-numeric ms
        "1700000000000-x",        # non-numeric seq
        "12; FLUSHALL",           # injection-ish
        "  1700000000000  ",      # surrounding whitespace
    ],
)
def test_normalize_maps_malformed_to_only_new(raw):
    # A malformed / hostile Last-Event-ID must NOT be forwarded to XREAD verbatim;
    # it falls back to "$" (only new events) rather than erroring or replaying.
    assert store._normalize_last_id(raw) == "$"
