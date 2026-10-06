import hashlib
import hmac

from src.security import (
    canonical_v2,
    event_id_for,
    ordering_key_for,
    sign_v2,
    token_matches,
)


def test_token_matching_requires_exact_non_empty_value():
    assert token_matches("a" * 32, "a" * 32)
    assert not token_matches("a" * 31, "a" * 32)
    assert not token_matches("", "")


def test_event_id_prefers_event_and_message_id():
    expected = hashlib.sha256(b"message_created:123").hexdigest()
    assert event_id_for({"event": "message_created", "message": {"id": 123}}, b"ignored") == expected


def test_event_id_supports_chatwoot_311_flat_message():
    expected = hashlib.sha256(b"message_created:123").hexdigest()
    assert event_id_for({"event": "message_created", "id": 123}, b"ignored") == expected


def test_event_id_falls_back_to_raw_body_hash():
    body = b'{"event":"conversation_updated"}'
    assert event_id_for({"event": "conversation_updated"}, body) == hashlib.sha256(body).hexdigest()


def test_ordering_key_prefers_chatwoot_conversation_id():
    assert ordering_key_for({"conversation": {"id": 42}}, "e" * 64) == "42"
    assert ordering_key_for({"conversation": {"id": "conv-42"}}, "e" * 64) == "conv-42"


def test_ordering_key_falls_back_for_missing_empty_or_structured_id():
    event_id = "e" * 64
    assert ordering_key_for({}, event_id) == event_id
    assert ordering_key_for({"conversation": {"id": "  "}}, event_id) == event_id
    assert ordering_key_for({"conversation": {"id": {"nested": 1}}}, event_id) == event_id


def test_v2_signature_binds_timestamp_event_and_body():
    body = b'{"event":"message_created"}'
    canonical = b"1700000000\n" + b"a" * 64 + b"\n" + body
    assert canonical_v2("1700000000", "a" * 64, body) == canonical
    expected = hmac.new(b"secret", canonical, hashlib.sha256).hexdigest()
    assert sign_v2("secret", "1700000000", "a" * 64, body) == f"sha256={expected}"
