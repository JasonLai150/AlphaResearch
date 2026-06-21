"""Token event contract — the wire member the typewriter UI matches on.

Pure unit tests of EventType.token and the EventEnvelope that carries a
streaming text delta. No Redis — mirrors tests/test_error_event.py.
"""

from __future__ import annotations

from infra.schemas import EventEnvelope, EventType


def test_token_member_exists_and_value():
    assert EventType.token == "token"
    assert EventType.token.value == "token"
    assert EventType("token") is EventType.token


def test_token_envelope_round_trips_through_json():
    env = EventEnvelope(
        session_id="s_1",
        job_id="j_1",
        type=EventType.token,
        payload={"msg_id": "msg_1#0", "role": "assistant", "delta": "hel", "final": False},
    )
    again = EventEnvelope.model_validate_json(env.model_dump_json())
    assert again.type is EventType.token
    assert again.payload == {
        "msg_id": "msg_1#0",
        "role": "assistant",
        "delta": "hel",
        "final": False,
    }
