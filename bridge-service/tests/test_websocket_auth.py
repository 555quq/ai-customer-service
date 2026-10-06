"""WebSocket authentication tests without starting external services."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request, WebSocketDisconnect

from src.auth.models import AuthUser
from src.auth.tokens import create_access_token, create_widget_token
from src.config import settings
from src.main import (
    manager,
    require_widget_request_token,
    websocket_agent,
    websocket_widget,
)


@pytest.fixture(autouse=True)
def auth_settings(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-with-at-least-32-characters")
    monkeypatch.setattr(settings, "jwt_issuer", "test-issuer")
    monkeypatch.setattr(settings, "jwt_audience", "test-audience")
    manager.active_connections.clear()
    yield
    manager.active_connections.clear()


def fake_websocket(token: str | None, conversation_id: str = "") -> MagicMock:
    websocket = MagicMock()
    websocket.query_params = {"conversation_id": conversation_id}
    websocket.accept = AsyncMock()
    websocket.close = AsyncMock()
    frame = {"type": "auth", "token": token} if token else {"type": "ping"}
    websocket.receive_json = AsyncMock(return_value=frame)
    websocket.receive_text = AsyncMock(side_effect=WebSocketDisconnect())
    return websocket


@pytest.mark.asyncio
async def test_agent_websocket_accepts_agent_access_token():
    token, _ = create_access_token(AuthUser(id="agent-1", username="agent", role="agent"))
    websocket = fake_websocket(token)

    await websocket_agent(websocket)

    websocket.accept.assert_awaited_once()
    websocket.close.assert_not_awaited()
    assert manager.active_connections == {}


@pytest.mark.asyncio
async def test_agent_websocket_rejects_widget_token():
    token, _ = create_widget_token("visitor-1", "42")
    websocket = fake_websocket(token)

    await websocket_agent(websocket)

    websocket.close.assert_awaited_once_with(code=4401, reason="Invalid credentials")


@pytest.mark.asyncio
async def test_widget_websocket_requires_matching_handoff():
    token, _ = create_widget_token("visitor-1", "42")
    matching = fake_websocket(token, "42")
    mismatched = fake_websocket(token, "43")

    await websocket_widget(matching)
    await websocket_widget(mismatched)

    matching.close.assert_not_awaited()
    mismatched.close.assert_awaited_once_with(code=4401, reason="Invalid capability")


def test_widget_http_capability_is_required_and_scope_bound():
    token, _ = create_widget_token("visitor-1", "42")
    request = Request(
        {
            "type": "http",
            "headers": [(b"authorization", f"Bearer {token}".encode())],
        }
    )
    require_widget_request_token(request, "visitor-1", "42")

    with pytest.raises(HTTPException) as mismatch:
        require_widget_request_token(request, "visitor-2", "42")
    assert mismatch.value.status_code == 403

    missing = Request({"type": "http", "headers": []})
    with pytest.raises(HTTPException) as unauthorized:
        require_widget_request_token(missing, "visitor-1", "42")
    assert unauthorized.value.status_code == 401
