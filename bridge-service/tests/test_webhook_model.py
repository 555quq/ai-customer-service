"""Compatibility tests for stock Chatwoot webhook payloads."""

from src.models.webhook import ChatwootWebhook


def test_chatwoot_311_flat_message_is_normalized():
    payload = {
        "event": "message_created",
        "id": 112,
        "content": "需要产品帮助",
        "message_type": "incoming",
        "private": False,
        "created_at": "2026-08-31T17:42:31.162Z",
        "sender": {"id": 32, "name": "访客"},
        "conversation": {"id": 23, "status": "open"},
    }

    webhook = ChatwootWebhook.model_validate(payload)

    assert webhook.message is not None
    assert webhook.message.id == 112
    assert webhook.message.content == "需要产品帮助"
    assert webhook.conversation.id == 23


def test_nested_message_payload_remains_supported():
    payload = {
        "event": "message_created",
        "id": 1,
        "message": {
            "id": 112,
            "content": "需要产品帮助",
            "message_type": "incoming",
            "private": False,
            "created_at": 1788198151,
            "sender": {"id": 32, "name": "访客"},
        },
        "conversation": {"id": 23, "status": "open"},
    }

    webhook = ChatwootWebhook.model_validate(payload)

    assert webhook.message.id == 112
