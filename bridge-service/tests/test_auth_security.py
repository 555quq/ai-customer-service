"""Authentication and Chatwoot webhook security tests."""
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

import src.main as main
from src.config import settings
from src.utils.auth import verify_api_key, verify_webhook_signature
from src.services.webhook_idempotency import Claim


WEBHOOK_SECRET = "webhook-test-secret"
EVENT_ID = hashlib.sha256(b"event-12345").hexdigest()


def raw_payload(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def signed_headers(
    payload: bytes,
    timestamp: int | None = None,
    event_id: str = EVENT_ID,
) -> dict[str, str]:
    timestamp_value = str(timestamp if timestamp is not None else int(time.time()))
    canonical = timestamp_value.encode() + b"\n" + event_id.encode() + b"\n" + payload
    headers = {
        "Content-Type": "application/json",
        "X-Chatwoot-Signature-Version": "v2",
        "X-Chatwoot-Timestamp": timestamp_value,
        "X-Chatwoot-Event-Id": event_id,
        "X-Chatwoot-Signature": hmac.new(
            WEBHOOK_SECRET.encode("utf-8"), canonical, hashlib.sha256
        ).hexdigest(),
    }
    return headers


@pytest.mark.asyncio
async def test_webhook_signature_accepts_exact_raw_body(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "chatwoot_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "webhook_require_timestamp", True)
    monkeypatch.setattr(settings, "webhook_timestamp_tolerance_seconds", 300)

    payload = b'{"event":"message_created"}'
    timestamp = str(int(time.time()))
    canonical = timestamp.encode() + b"\n" + EVENT_ID.encode() + b"\n" + payload
    signature = hmac.new(WEBHOOK_SECRET.encode(), canonical, hashlib.sha256).hexdigest()

    assert await verify_webhook_signature(
        signature, payload, timestamp, version="v2", event_id=EVENT_ID
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "signature,timestamp",
    [
        (None, str(int(time.time()))),
        ("0" * 64, str(int(time.time()))),
        ("not-a-signature", str(int(time.time()))),
        (None, None),
        ("0" * 64, str(int(time.time()) - 301)),
    ],
)
async def test_webhook_signature_rejects_missing_invalid_or_replayed_request(
    monkeypatch, signature, timestamp
):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "chatwoot_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "webhook_require_timestamp", True)
    monkeypatch.setattr(settings, "webhook_timestamp_tolerance_seconds", 300)

    assert not await verify_webhook_signature(
        signature, b"{}", timestamp, version="v2", event_id=EVENT_ID
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["body", "timestamp", "event_id", "version"])
async def test_v2_rejects_any_tampered_signed_field(monkeypatch, field):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "chatwoot_webhook_secret", WEBHOOK_SECRET)
    timestamp = str(int(time.time()))
    payload = b'{"event":"message_created"}'
    canonical = timestamp.encode() + b"\n" + EVENT_ID.encode() + b"\n" + payload
    signature = hmac.new(WEBHOOK_SECRET.encode(), canonical, hashlib.sha256).hexdigest()
    values = {
        "payload": payload,
        "timestamp": timestamp,
        "event_id": EVENT_ID,
        "version": "v2",
    }
    if field == "body":
        values["payload"] = payload + b" "
    elif field == "timestamp":
        values["timestamp"] = str(int(timestamp) - 1)
    elif field == "event_id":
        values["event_id"] = "a" * 64
    else:
        values["version"] = "v1"

    assert not await verify_webhook_signature(
        signature,
        values["payload"],
        values["timestamp"],
        version=values["version"],
        event_id=values["event_id"],
    )


@pytest.mark.asyncio
async def test_development_can_disable_required_timestamp_but_not_signature_check(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "chatwoot_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "webhook_require_timestamp", False)
    monkeypatch.setattr(settings, "webhook_allow_legacy_v1", True)

    payload = b"{}"
    valid_signature = hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256
    ).hexdigest()

    assert await verify_webhook_signature(valid_signature, payload)
    assert not await verify_webhook_signature("0" * 64, payload)


@pytest.mark.asyncio
async def test_production_rejects_legacy_v1_even_when_compatibility_is_enabled(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "chatwoot_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "webhook_allow_legacy_v1", True)
    payload = b"{}"
    signature = hmac.new(WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()

    assert not await verify_webhook_signature(
        signature, payload, str(int(time.time())), version="v1"
    )


@pytest.mark.asyncio
async def test_development_without_secret_keeps_unsigned_compatibility(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "chatwoot_webhook_secret", None)

    assert await verify_webhook_signature(None, b"{}")
    assert not await verify_webhook_signature("invalid", b"{}")


@pytest.mark.asyncio
async def test_api_key_matching_strips_config_whitespace_without_logging_secret(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "api_keys", " first-key, second-key ")

    assert await verify_api_key("second-key") == "second-key"


def test_production_login_rejects_missing_api_key(test_client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "api_keys", None)

    response = test_client.post(
        "/api/auth/login",
        json={
            "username": settings.admin_username,
            "password": settings.admin_password,
            "role": "admin",
        },
    )

    assert response.status_code == 503
    assert "token" not in response.text.lower()


def test_development_login_uses_ephemeral_token(test_client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "api_keys", None)

    response = test_client.post(
        "/api/auth/login",
        json={
            "username": settings.agent_username,
            "password": settings.agent_password,
            "role": "agent",
        },
    )

    assert response.status_code == 200
    token = response.json()["token"]
    assert token != "dev-token"
    assert len(token) >= 32


def test_webhook_valid_signature_is_checked_before_processing(
    test_client: TestClient,
    sample_chatwoot_webhook_payload: dict,
    monkeypatch,
):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "chatwoot_webhook_secret", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "webhook_require_timestamp", True)
    monkeypatch.setattr(settings, "webhook_timestamp_tolerance_seconds", 300)
    process_message = AsyncMock(
        return_value={
            "action": "ai_replied",
            "intent": "question",
            "confidence": 0.95,
            "response_time_ms": 1,
        }
    )
    monkeypatch.setattr(main, "process_message", process_message)
    idempotency = AsyncMock()
    idempotency.claim.return_value = Claim("claimed", "owner-token")
    monkeypatch.setattr(main, "webhook_idempotency", idempotency)

    body = raw_payload(sample_chatwoot_webhook_payload)
    response = test_client.post(
        "/webhook/chatwoot",
        data=body,
        headers=signed_headers(body, int(time.time())),
    )

    assert response.status_code == 200
    process_message.assert_awaited_once()
    idempotency.complete.assert_awaited_once_with(EVENT_ID, "owner-token")


def test_webhook_invalid_signature_never_reaches_processing(
    test_client: TestClient,
    sample_chatwoot_webhook_payload: dict,
    monkeypatch,
):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "chatwoot_webhook_secret", WEBHOOK_SECRET)
    process_message = AsyncMock()
    monkeypatch.setattr(main, "process_message", process_message)

    body = raw_payload(sample_chatwoot_webhook_payload)
    headers = signed_headers(body, int(time.time()))
    headers["X-Chatwoot-Signature"] = "0" * 64

    response = test_client.post("/webhook/chatwoot", data=body, headers=headers)

    assert response.status_code == 401
    process_message.assert_not_awaited()


def test_webhook_invalid_json_preserves_422(
    test_client: TestClient,
    monkeypatch,
):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "chatwoot_webhook_secret", WEBHOOK_SECRET)
    body = b'{"event":'

    response = test_client.post(
        "/webhook/chatwoot",
        data=body,
        headers=signed_headers(body, int(time.time())),
    )

    assert response.status_code == 422
