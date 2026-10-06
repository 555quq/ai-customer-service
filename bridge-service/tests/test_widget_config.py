from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import src.main as main
from src.auth.tokens import validate_widget_token
from src.config import settings
from src.routes import widget as widget_routes
from src.services.handoff_store import (
    HandoffRecord,
    HandoffSessionNotRestorable,
    HandoffStoreUnavailable,
    HandoffVisitorMismatch,
)
from src.utils.config_manager import config_manager


WIDGET_RUNTIME = {
    "setup": {"initialized": True},
    "site": {"name": "Acme 客服", "brand_color": "#123456", "locale": "zh-CN"},
    "ai_rules": {"welcome_message": "欢迎咨询"},
    "widget": {"site_token": "public-site-token", "theme": "light", "position": "right"},
    "allowed_origins": ["https://www.example.com"],
}


def _configure(monkeypatch):
    monkeypatch.setattr(config_manager, "config", deepcopy(WIDGET_RUNTIME))
    monkeypatch.setattr(
        main,
        "handoff_store",
        SimpleNamespace(
            get_chatwoot_conversation_id=AsyncMock(return_value=None),
        ),
    )

    async def no_handoff(_conversation_id: str, _visitor_id: str):
        return None

    widget_routes.set_handoff_resolver(no_handoff)


def _admin_headers(test_client):
    response = test_client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123", "role": "admin"},
    )
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _production_admin_headers(test_client, monkeypatch):
    # Production token validation requires an explicitly strong signing key.
    monkeypatch.setattr(settings, "jwt_secret", "test-only-" * 8)
    return _admin_headers(test_client)


def test_public_config_requires_matching_site_and_origin(test_client, monkeypatch):
    _configure(monkeypatch)
    denied = test_client.get(
        "/api/widget/config",
        headers={"Origin": "https://evil.example", "X-Site-Token": "public-site-token"},
    )
    assert denied.status_code == 403

    result = test_client.get(
        "/api/widget/config",
        headers={"Origin": "https://www.example.com", "X-Site-Token": "public-site-token"},
    )
    assert result.status_code == 200
    assert result.json()["brandName"] == "Acme 客服"
    assert "site_token" not in result.text
    assert result.headers["access-control-allow-origin"] == "https://www.example.com"


def test_widget_session_is_scoped_and_required_for_chat(test_client, monkeypatch):
    _configure(monkeypatch)
    main.ai_engine.chat = AsyncMock(return_value=SimpleNamespace(reply="您好", confidence=0.95))
    common_headers = {"Origin": "https://www.example.com", "X-Site-Token": "public-site-token"}
    session = test_client.post(
        "/api/widget/session",
        headers=common_headers,
        json={"conversation_id": "conversation-123", "visitor_id": "visitor-123"},
    )
    assert session.status_code == 200
    capability = session.json()["capability_token"]
    assert session.json()["handoff"] is False
    assert session.json()["chatwoot_conversation_id"] is None

    missing = test_client.post(
        "/api/chat",
        headers={"Origin": "https://www.example.com"},
        json={"message": "你好", "conversation_id": "conversation-123", "user_id": "visitor-123"},
    )
    assert missing.status_code == 401

    accepted = test_client.post(
        "/api/chat",
        headers={"Origin": "https://www.example.com", "Authorization": f"Bearer {capability}"},
        json={"message": "你好", "conversation_id": "conversation-123", "user_id": "visitor-123"},
    )
    assert accepted.status_code == 200

    wrong_scope = test_client.post(
        "/api/chat",
        headers={"Origin": "https://www.example.com", "Authorization": f"Bearer {capability}"},
        json={"message": "你好", "conversation_id": "conversation-999", "user_id": "visitor-123"},
    )
    assert wrong_scope.status_code == 403


def test_widget_session_restores_scoped_handoff_capability(test_client, monkeypatch):
    _configure(monkeypatch)

    async def restore(_conversation_id: str, _visitor_id: str):
        return HandoffRecord(chatwoot_conversation_id="42")

    widget_routes.set_handoff_resolver(restore)
    response = test_client.post(
        "/api/widget/session",
        headers={"Origin": "https://www.example.com", "X-Site-Token": "public-site-token"},
        json={"conversation_id": "conversation-123", "visitor_id": "visitor-123"},
    )

    assert response.status_code == 200
    assert response.json()["handoff"] is True
    assert response.json()["chatwoot_conversation_id"] == "42"
    claims = validate_widget_token(
        response.json()["capability_token"],
        "conversation-123",
        "42",
    )
    assert claims.chatwoot_conversation_id == "42"


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (HandoffVisitorMismatch(), 403, "HANDOFF_VISITOR_MISMATCH"),
        (HandoffSessionNotRestorable(), 409, "HANDOFF_SESSION_NOT_RESTORABLE"),
        (HandoffStoreUnavailable(), 503, "HANDOFF_STORE_UNAVAILABLE"),
    ],
)
def test_widget_session_fails_closed_for_handoff_resolution_errors(
    test_client,
    monkeypatch,
    error,
    status_code,
    code,
):
    _configure(monkeypatch)

    async def fail(_conversation_id: str, _visitor_id: str):
        raise error

    widget_routes.set_handoff_resolver(fail)
    response = test_client.post(
        "/api/widget/session",
        headers={"Origin": "https://www.example.com", "X-Site-Token": "public-site-token"},
        json={"conversation_id": "conversation-123", "visitor_id": "visitor-123"},
    )

    assert response.status_code == status_code
    assert response.json()["detail"]["code"] == code


def test_widget_snippet_requires_admin_and_contains_only_public_site_token(test_client, monkeypatch):
    _configure(monkeypatch)
    denied = test_client.get("/api/widget/snippet")
    assert denied.status_code == 401
    result = test_client.get("/api/widget/snippet", headers=_admin_headers(test_client))
    assert result.status_code == 200
    snippet = result.json()["snippet"]
    assert 'data-site-token="public-site-token"' in snippet
    assert "model-secret" not in snippet


def test_widget_preflight_rejects_unknown_origin(test_client, monkeypatch):
    _configure(monkeypatch)
    response = test_client.options(
        "/api/widget/session",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Headers": "X-Site-Token"},
    )
    assert response.status_code == 403


def test_widget_snippet_uses_explicit_public_base_in_production(test_client, monkeypatch):
    headers = _production_admin_headers(test_client, monkeypatch)
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "widget_host", "widget.example.com")
    monkeypatch.setattr(settings, "widget_public_base_url", "https://widget.example.com")
    monkeypatch.setitem(widget_routes.config_manager.config["widget"], "asset_url", "https://evil.example/widget.js")

    result = test_client.get("/api/widget/snippet", headers=headers)

    assert result.status_code == 200
    assert result.json()["api_base"] == "https://widget.example.com"
    assert result.json()["asset_url"] == "https://widget.example.com/assets/widget.js"
    assert "evil.example" not in result.text


def test_widget_snippet_fails_closed_when_production_public_base_is_missing(test_client, monkeypatch):
    headers = _production_admin_headers(test_client, monkeypatch)
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "widget_host", "widget.example.com")
    monkeypatch.setattr(settings, "widget_public_base_url", None)
    monkeypatch.setitem(widget_routes.config_manager.config["widget"], "api_base", "http://admin:8080")

    result = test_client.get("/api/widget/snippet", headers=headers)

    assert result.status_code == 409
    assert result.json()["detail"]["code"] == "WIDGET_PUBLIC_URL_NOT_CONFIGURED"
    assert "admin:8080" not in result.text


@pytest.mark.parametrize("public_url", [
    "http://widget.example.com",
    "https://widget.example.com/path",
    "https://other.example.com",
    "https://widget.example.com?leak=1",
])
def test_widget_snippet_rejects_invalid_production_public_base(test_client, monkeypatch, public_url):
    headers = _production_admin_headers(test_client, monkeypatch)
    _configure(monkeypatch)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "widget_host", "widget.example.com")
    monkeypatch.setattr(settings, "widget_public_base_url", public_url)

    result = test_client.get("/api/widget/snippet", headers=headers)

    assert result.status_code == 500
    assert result.json()["detail"]["code"] == "WIDGET_PUBLIC_URL_INVALID"
