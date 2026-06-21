"""Local-sim assistant messages stream as token deltas (typewriter), and the
deltas reconstruct the original text exactly. Captures emit/append via
monkeypatch + a no-op sleep — no timing, no real Redis needed.
"""

from __future__ import annotations

import asyncio

import pytest

from infra import store
from infra.schemas import EventType
from runner import local_sim


def test_chunk_text_reconstructs_exactly():
    text = "Curiosity cracked the key-door chaining at 0.81 success."
    chunks = local_sim._chunk_text(text)
    assert len(chunks) > 1            # actually chunked, not one blob
    assert "".join(chunks) == text    # deltas concatenate back to the original


def test_chunk_text_empty_is_no_chunks():
    assert local_sim._chunk_text("") == []


def test_chunk_text_single_word():
    assert local_sim._chunk_text("hello") == ["hello"]


def test_chunk_text_preserves_leading_and_trailing_whitespace():
    text = "  hello   world  "
    assert "".join(local_sim._chunk_text(text)) == text


@pytest.mark.asyncio
async def test_stream_assistant_emits_tokens_then_persists(monkeypatch):
    events = []
    messages = []

    async def fake_emit(ev):
        events.append(ev)

    async def fake_append(m):
        messages.append(m)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(store, "emit_event", fake_emit)
    monkeypatch.setattr(store, "append_message", fake_append)
    monkeypatch.setattr(local_sim.asyncio, "sleep", no_sleep)

    content = "X is the clear winner here."
    await local_sim._stream_assistant("s1", "root", content)

    assert events, "expected token events"
    assert all(e.type is EventType.token for e in events)
    # One stable msg_id across the whole message.
    assert len({e.payload["msg_id"] for e in events}) == 1
    # Deltas reconstruct the content; only the last is final.
    assert "".join(e.payload["delta"] for e in events) == content
    assert [e.payload["final"] for e in events][-1] is True
    assert all(f is False for f in [e.payload["final"] for e in events][:-1])
    # The full message is persisted once for the /full snapshot.
    assert len(messages) == 1
    assert messages[0].role == "assistant" and messages[0].content == content
