"""Token, event identity, and HMAC v2 helpers."""

import hashlib
import hmac
import json
from typing import Any


def token_matches(candidate: str, expected: str) -> bool:
    if not candidate or not expected:
        return False
    return hmac.compare_digest(candidate.encode("utf-8"), expected.encode("utf-8"))


def parse_json_object(raw_body: bytes) -> dict[str, Any]:
    value = json.loads(raw_body)
    if not isinstance(value, dict):
        raise ValueError("Webhook payload must be a JSON object")
    return value


def event_id_for(payload: dict[str, Any], raw_body: bytes) -> str:
    event = payload.get("event")
    message = payload.get("message")
    message_id = message.get("id") if isinstance(message, dict) else None
    if message_id is None and event == "message_created":
        message_id = payload.get("id")
    if isinstance(event, str) and event and message_id is not None:
        source = f"{event}:{message_id}".encode("utf-8")
    else:
        source = raw_body
    return hashlib.sha256(source).hexdigest()


def ordering_key_for(payload: dict[str, Any], event_id: str) -> str:
    conversation = payload.get("conversation")
    candidate = conversation.get("id") if isinstance(conversation, dict) else None
    if isinstance(candidate, bool) or not isinstance(candidate, (str, int)):
        return event_id
    value = str(candidate).strip()
    return value[:128] if value else event_id


def canonical_v2(timestamp: str, event_id: str, raw_body: bytes) -> bytes:
    return timestamp.encode("ascii") + b"\n" + event_id.encode("ascii") + b"\n" + raw_body


def sign_v2(secret: str, timestamp: str, event_id: str, raw_body: bytes) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        canonical_v2(timestamp, event_id, raw_body),
        hashlib.sha256,
    ).hexdigest()
    return f"sha256={digest}"
