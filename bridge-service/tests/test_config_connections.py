from unittest.mock import AsyncMock, MagicMock

import httpx

from src.routes import config as config_routes
from src.utils.config_manager import ConfigManager, sanitize_config


def _admin_headers(test_client):
    response = test_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123", "role": "admin"},
    )
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _mock_async_client(monkeypatch, response):
    client = AsyncMock()
    client.get.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    context.__aexit__.return_value = False
    factory = MagicMock(return_value=context)
    monkeypatch.setattr(config_routes.httpx, "AsyncClient", factory)
    return client


def test_sanitize_config_masks_nested_secrets():
    sanitized = sanitize_config({
        "ai": {"api_key": "sk-" + "1234567890", "model": "deepseek-chat"},
        "chatwoot_token": "abcdefghijk",
    })
    assert sanitized["ai"]["api_key"] == "sk-***890"
    assert sanitized["ai"]["model"] == "deepseek-chat"
    assert sanitized["chatwoot_token"] == "abc***ijk"


def test_model_connection_reports_models(test_client, monkeypatch):
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://model.example/v1/models"),
        json={"data": [{"id": "deepseek-chat"}]},
    )
    _mock_async_client(monkeypatch, response)
    result = test_client.post(
        "/api/config/test-model",
        headers=_admin_headers(test_client),
        json={"api_base": "https://model.example/v1", "api_key": "secret", "model": "deepseek-chat"},
    )
    assert result.status_code == 200
    assert result.json()["model_available"] is True


def test_model_connection_maps_auth_error(test_client, monkeypatch):
    request = httpx.Request("GET", "https://model.example/v1/models")
    response = httpx.Response(401, request=request)
    response.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError("unauthorized", request=request, response=response))
    _mock_async_client(monkeypatch, response)
    result = test_client.post(
        "/api/config/test-model",
        headers=_admin_headers(test_client),
        json={"api_base": "https://model.example/v1", "api_key": "bad"},
    )
    assert result.status_code == 502
    assert result.json()["detail"]["code"] == "MODEL_AUTH_FAILED"


def test_chatwoot_connection_checks_inbox(test_client, monkeypatch):
    response = httpx.Response(
        200,
        request=httpx.Request("GET", "https://chat.example/api/v1/accounts/1/inboxes"),
        json={"payload": [{"id": 3, "name": "Website"}]},
    )
    _mock_async_client(monkeypatch, response)
    result = test_client.post(
        "/api/config/test-chatwoot",
        headers=_admin_headers(test_client),
        json={
            "base_url": "https://chat.example",
            "api_token": "secret",
            "account_id": "1",
            "inbox_id": 3,
        },
    )
    assert result.status_code == 200
    assert result.json()["inbox_available"] is True


def test_connection_routes_require_admin(test_client):
    result = test_client.post(
        "/api/config/test-model",
        json={"api_base": "https://model.example/v1", "api_key": "secret"},
    )
    assert result.status_code == 401


def test_single_key_config_read_is_sanitized(test_client, monkeypatch, tmp_path):
    manager = ConfigManager(str(tmp_path / "runtime.json"), encryption_key="11" * 32)
    manager.update({"model": {"api_key": "model-secret-value"}})
    monkeypatch.setattr(config_routes, "config_manager", manager)

    result = test_client.get(
        "/api/config?key=model.api_key",
        headers=_admin_headers(test_client),
    )

    assert result.status_code == 200
    assert result.json() == {"key": "model.api_key", "value": "mod***lue"}


def test_batch_config_expands_dotted_keys(test_client, monkeypatch, tmp_path):
    manager = ConfigManager(str(tmp_path / "runtime.json"), encryption_key="11" * 32)
    monkeypatch.setattr(config_routes, "config_manager", manager)

    result = test_client.post(
        "/api/config/batch",
        headers=_admin_headers(test_client),
        json={"config": {"ai.confidence_threshold": 0.81, "cache.ttl": 7200}},
    )

    assert result.status_code == 200
    assert manager.get("ai.confidence_threshold") == 0.81
    assert manager.get("cache.ttl") == 7200
    assert "ai.confidence_threshold" not in manager.config


def test_batch_config_rolls_back_when_runtime_apply_fails(test_client, monkeypatch, tmp_path):
    manager = ConfigManager(str(tmp_path / "runtime.json"), encryption_key="11" * 32)
    manager.update({"setup": {"initialized": True}, "ai": {"confidence_threshold": 0.7}})
    monkeypatch.setattr(config_routes, "config_manager", manager)
    monkeypatch.setattr(
        config_routes,
        "_runtime_apply_callback",
        AsyncMock(side_effect=RuntimeError("replacement failed")),
    )

    result = test_client.post(
        "/api/config/batch",
        headers=_admin_headers(test_client),
        json={"config": {"ai.confidence_threshold": 0.95}},
    )

    assert result.status_code == 500
    assert manager.get("ai.confidence_threshold") == 0.7
