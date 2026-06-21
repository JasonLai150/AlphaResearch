"""Error event contract (TASK #13).

Pure unit tests of the EventType.error member and the EventEnvelope shape that
carries it — no Redis (fake or real), no store imports, just the typed schemas.
Mirrors the no-redis style of tests/test_public_auth.py: isolate the contract,
leave the live bus to the end-to-end verification.
"""

from __future__ import annotations

from infra.schemas import EventEnvelope, EventType


def test_error_member_exists_and_value():
    # The UI relies on the literal string "error" on the wire.
    assert EventType.error == "error"
    assert EventType.error.value == "error"
    assert EventType("error") is EventType.error


def test_error_envelope_validates_with_reason_payload():
    env = EventEnvelope(
        session_id="s_1",
        job_id="j_1",
        type=EventType.error,
        payload={"reason": "local-sim error", "message": "boom"},
    )
    assert env.type is EventType.error
    assert env.payload["reason"] == "local-sim error"
    assert env.payload["message"] == "boom"


def test_error_envelope_round_trips_through_json():
    # Serialization keeps the "error" string so SSE consumers see the right type.
    env = EventEnvelope(
        session_id="s_2",
        job_id="j_2",
        type=EventType.error,
        payload={"reason": "local-sim reply error", "message": "nope"},
    )
    again = EventEnvelope.model_validate_json(env.model_dump_json())
    assert again.type is EventType.error
    assert again.payload == {"reason": "local-sim reply error", "message": "nope"}
