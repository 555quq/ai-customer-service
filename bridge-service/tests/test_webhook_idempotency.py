"""Webhook Redis idempotency tests."""

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock

import pytest

import src.main as main
from src.config import settings
from src.services.webhook_idempotency import (
    Claim,
    WebhookIdempotency,
    WebhookIdempotencyUnavailable,
)


SECRET = "webhook-idempotency-secret"
EVENT_ID = hashlib.sha256(b"idempotency-event").hexdigest()


def _headers(body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    canonical = timestamp.encode() + b"\n" + EVENT_ID.encode() + b"\n" + body
    return {
        "Content-Type": "application/json",
        "X-Chatwoot-Signature-Version": "v2",
        "X-Chatwoot-Timestamp": timestamp,
        "X-Chatwoot-Event-Id": EVENT_ID,
        "X-Chatwoot-Signature": "sha256=" + hmac.new(
            SECRET.encode(), canonical, hashlib.sha256
        ).hexdigest(),
    }


@pytest.mark.asyncio
async def test_claim_states_and_configured_ttls():
    client = AsyncMock()
    service = WebhookIdempotency(client, lock_seconds=600, done_seconds=604800)
    client.exists.return_value = False
    client.set.return_value = True

    claim = await service.claim(EVENT_ID)
    assert claim.status == "claimed"
    assert claim.owner
    client.set.assert_awaited_once_with(
        f"ai:bridge:webhook:lock:{EVENT_ID}", claim.owner, ex=600, nx=True
    )

    client.eval.return_value = 1
    await service.complete(EVENT_ID, claim.owner)
    assert client.eval.await_args.args[-1] == "604800"

    client.reset_mock()
    client.exists.return_value = True
    assert (await service.claim(EVENT_ID)).status == "duplicate"

    client.exists.return_value = False
    client.set.return_value = False
    assert (await service.claim(EVENT_ID)).status == "in_progress"


@pytest.mark.asyncio
async def test_missing_redis_fails_closed():
    service = WebhookIdempotency(None)
    with pytest.raises(WebhookIdempotencyUnavailable):
        await service.claim(EVENT_ID)


@pytest.mark.parametrize("claim_status,expected_status", [("duplicate", 200), ("in_progress", 409)])
def test_duplicate_or_concurrent_delivery_never_processes(
    test_client,
    sample_chatwoot_webhook_payload,
    monkeypatch,
    claim_status,
    expected_status,
):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "chatwoot_webhook_secret", SECRET)
    process_message = AsyncMock()
    monkeypatch.setattr(main, "process_message", process_message)
    idempotency = AsyncMock()
    idempotency.claim.return_value = Claim(claim_status)
    monkeypatch.setattr(main, "webhook_idempotency", idempotency)
    body = json.dumps(
        sample_chatwoot_webhook_payload, ensure_ascii=False, separators=(",", ":")
    ).encode()

    response = test_client.post("/webhook/chatwoot", data=body, headers=_headers(body))

    assert response.status_code == expected_status
    if claim_status == "duplicate":
        assert response.json() == {"status": "duplicate"}
    process_message.assert_not_awaited()


def test_production_returns_503_when_idempotency_store_is_unavailable(
    test_client, sample_chatwoot_webhook_payload, monkeypatch
):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "chatwoot_webhook_secret", SECRET)
    monkeypatch.setattr(main, "webhook_idempotency", None)
    body = json.dumps(
        sample_chatwoot_webhook_payload, ensure_ascii=False, separators=(",", ":")
    ).encode()

    response = test_client.post("/webhook/chatwoot", data=body, headers=_headers(body))

    assert response.status_code == 503
