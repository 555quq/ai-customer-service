import httpx
import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock

from src.config import settings
from src.services.setup_service import setup_service
from src.utils.config_manager import ConfigManager


def _payload(**overrides):
    payload = {
        "site": {"name": "示例企业", "brand_color": "#6366f1", "locale": "zh-CN"},
        "model": {
            "provider": "deepseek",
            "api_base": "https://model.example/v1",
            "api_key": "model-secret",
            "model": "deepseek-chat",
        },
        "chatwoot": {
            "base_url": "https://chat.example",
            "api_token": "chatwoot-secret",
            "account_id": "1",
            "inbox_id": 3,
        },
        "admin": {"username": "owner", "password": "a-secure-password"},
        "agent": {"username": "support", "password": "another-secure-password"},
        "ai_rules": {
            "welcome_message": "你好",
            "system_prompt": "请严格根据企业知识库回答客户问题。",
            "confidence_threshold": 0.7,
            "handoff_keywords": ["人工", "退款"],
        },
        "allowed_origins": ["https://www.example.com"],
        "verify_connections": False,
    }
    payload.update(overrides)
    return payload


def _isolated_setup(monkeypatch, tmp_path):
    manager = ConfigManager(str(tmp_path / "runtime.json"), encryption_key="11" * 32)
    monkeypatch.setattr(setup_service, "manager", manager)
    monkeypatch.setattr(settings, "setup_token", "one-time-token")
    register = AsyncMock(
        return_value={
            "id": 42,
            "name": setup_service.WEBHOOK_NAME,
            "status": "created",
        }
    )
    monkeypatch.setattr(setup_service, "_register_chatwoot_webhook", register)
    return manager


def test_setup_status_and_initialize_once(test_client, monkeypatch, tmp_path):
    manager = _isolated_setup(monkeypatch, tmp_path)
    status = test_client.get("/api/setup/status")
    assert status.status_code == 200
    assert status.json()["initialized"] is False
    assert status.json()["agent_credentials_configured"] is False
    assert status.json()["version"] == 2

    result = test_client.post(
        "/api/setup/initialize",
        headers={"X-Setup-Token": "one-time-token"},
        json=_payload(),
    )
    assert result.status_code == 201
    assert manager.get("setup.initialized") is True
    assert manager.get("site.name") == "示例企业"
    assert manager.get("auth.admin.password_hash").startswith("$argon2")
    assert manager.get("auth.agent.username") == "support"
    assert manager.get("auth.agent.password_hash").startswith("$argon2")
    assert manager.get("integrations.chatwoot_webhook.id") == 42
    persisted = manager.config_file.read_text(encoding="utf-8")
    assert "a-secure-password" not in persisted
    assert "another-secure-password" not in persisted
    assert "model-secret" not in persisted
    assert "chatwoot-secret" not in persisted
    assert "fernet:v1:" in persisted

    repeated = test_client.post(
        "/api/setup/initialize",
        headers={"X-Setup-Token": "one-time-token"},
        json=_payload(),
    )
    assert repeated.status_code == 409
    assert repeated.json()["detail"]["code"] == "SETUP_ALREADY_COMPLETED"


def test_setup_rejects_invalid_token_without_writing(test_client, monkeypatch, tmp_path):
    manager = _isolated_setup(monkeypatch, tmp_path)
    result = test_client.post(
        "/api/setup/initialize",
        headers={"X-Setup-Token": "wrong"},
        json=_payload(),
    )
    assert result.status_code == 401
    assert manager.get("setup.initialized", False) is False


def test_setup_validation_rejects_weak_admin_password(test_client, monkeypatch, tmp_path):
    _isolated_setup(monkeypatch, tmp_path)
    payload = _payload()
    payload["admin"]["password"] = "short"
    result = test_client.post(
        "/api/setup/initialize",
        headers={"X-Setup-Token": "one-time-token"},
        json=payload,
    )
    assert result.status_code == 422


def test_setup_validation_rejects_weak_agent_password(test_client, monkeypatch, tmp_path):
    _isolated_setup(monkeypatch, tmp_path)
    payload = _payload()
    payload["agent"]["password"] = "short"

    result = test_client.post(
        "/api/setup/initialize",
        headers={"X-Setup-Token": "one-time-token"},
        json=payload,
    )

    assert result.status_code == 422


def test_setup_probe_failure_does_not_persist(test_client, monkeypatch, tmp_path):
    manager = _isolated_setup(monkeypatch, tmp_path)
    payload = _payload()
    payload["verify_connections"] = True
    request = httpx.Request("GET", "https://model.example/v1/models")
    response = httpx.Response(401, request=request)

    async def fail_probe(_model):
        raise httpx.HTTPStatusError("unauthorized", request=request, response=response)

    monkeypatch.setattr(setup_service, "_probe_model", fail_probe)
    result = test_client.post(
        "/api/setup/initialize",
        headers={"X-Setup-Token": "one-time-token"},
        json=payload,
    )
    assert result.status_code == 502
    assert result.json()["detail"]["code"] == "UPSTREAM_AUTH_FAILED"
    assert manager.get("setup.initialized", False) is False


@pytest.mark.asyncio
async def test_setup_rejects_non_api_chatwoot_inbox(monkeypatch):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, headers):
            request = httpx.Request("GET", url, headers=headers)
            return httpx.Response(
                200,
                request=request,
                json={"payload": [{"id": 3, "channel_type": "Channel::WebWidget"}]},
            )

    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: FakeClient())

    with pytest.raises(HTTPException) as exc_info:
        await setup_service._probe_chatwoot(_payload()["chatwoot"])

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "CHATWOOT_API_INBOX_REQUIRED"


class _WebhookClient:
    def __init__(self, listed, calls, result_id=77):
        self.listed = listed
        self.calls = calls
        self.result_id = result_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url, headers=None):
        self.calls.append(("GET", url, headers, None))
        request = httpx.Request("GET", url, headers=headers)
        if url.endswith("/ready"):
            return httpx.Response(200, request=request, json={"status": "ready"})
        return httpx.Response(200, request=request, json=self.listed)

    async def post(self, url, headers=None, json=None):
        self.calls.append(("POST", url, headers, json))
        return httpx.Response(
            200, request=httpx.Request("POST", url), json={"id": self.result_id}
        )

    async def patch(self, url, headers=None, json=None):
        self.calls.append(("PATCH", url, headers, json))
        return httpx.Response(
            200, request=httpx.Request("PATCH", url), json={"id": self.result_id}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "listed,expected_method",
    [
        ({"payload": {"webhooks": []}}, "POST"),
        ([{"id": 77, "name": setup_service.WEBHOOK_NAME}], "PATCH"),
        (
            {
                "payload": {
                    "webhooks": [
                        {
                            "id": 77,
                            "url": "http://webhook-gateway:8080/webhook/private-ingress-token",
                            "subscriptions": ["message_created"],
                        }
                    ]
                }
            },
            "PATCH",
        ),
    ],
)
async def test_register_webhook_creates_or_updates_exact_name(
    monkeypatch, listed, expected_method
):
    calls = []
    client = _WebhookClient(listed, calls)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(settings, "chatwoot_adapter_gateway_url", "http://webhook-gateway:8080")
    monkeypatch.setattr(settings, "chatwoot_adapter_ingress_token", "private-ingress-token")

    result = await setup_service._register_chatwoot_webhook(_payload()["chatwoot"])

    mutation = next(call for call in calls if call[0] in {"POST", "PATCH"})
    assert mutation[0] == expected_method
    assert mutation[3]["subscriptions"] == ["message_created"]
    assert mutation[3]["name"] == setup_service.WEBHOOK_NAME
    assert result["id"] == 77
    assert "url" not in result


@pytest.mark.asyncio
async def test_register_webhook_rejects_duplicate_product_names(monkeypatch):
    duplicate = {"id": 1, "name": setup_service.WEBHOOK_NAME}
    calls = []
    client = _WebhookClient([duplicate, {**duplicate, "id": 2}], calls)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr(settings, "chatwoot_adapter_gateway_url", "http://webhook-gateway:8080")
    monkeypatch.setattr(settings, "chatwoot_adapter_ingress_token", "private-ingress-token")

    with pytest.raises(HTTPException) as exc_info:
        await setup_service._register_chatwoot_webhook(_payload()["chatwoot"])

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == {"code": "CHATWOOT_WEBHOOK_NAME_CONFLICT"}
    assert not any(call[0] in {"POST", "PATCH"} for call in calls)
