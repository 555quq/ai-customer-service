"""Authentication routes and RBAC matrix tests without external services."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.auth.dependencies import require_admin, require_agent
from src.auth.routes import configure_session_store, router
from src.auth import passwords
from src.config import settings


@pytest.fixture
def auth_client(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "jwt_secret", "route-test-secret-with-at-least-32-characters")
    monkeypatch.setattr(settings, "jwt_issuer", "route-test-issuer")
    monkeypatch.setattr(settings, "jwt_audience", "route-test-audience")
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "admin-password")
    monkeypatch.setattr(settings, "admin_password_hash", None)
    monkeypatch.setattr(settings, "agent_username", "agent")
    monkeypatch.setattr(settings, "agent_password", "agent-password")
    monkeypatch.setattr(settings, "agent_password_hash", None)
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    monkeypatch.setattr(settings, "refresh_cookie_name", "ai_cs_refresh")
    monkeypatch.setattr(settings, "admin_refresh_cookie_name", "ai_cs_refresh_admin", raising=False)
    monkeypatch.setattr(settings, "agent_refresh_cookie_name", "ai_cs_refresh_agent", raising=False)
    configure_session_store(None)

    app = FastAPI()
    app.include_router(router)

    @app.get("/agent-only", dependencies=[Depends(require_agent)])
    async def agent_only():
        return {"ok": True}

    @app.get("/admin-only", dependencies=[Depends(require_admin)])
    async def admin_only():
        return {"ok": True}

    with TestClient(app) as client:
        yield client


def login(client: TestClient, role: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={
            "username": role,
            "password": f"{role}-password",
            "role": role,
        },
    )
    assert response.status_code == 200
    return response.json()


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_login_me_refresh_and_logout(auth_client: TestClient):
    logged_in = login(auth_client, "admin")
    assert logged_in["user"]["role"] == "admin"
    assert logged_in["expires_in"] == 1800
    assert auth_client.cookies.get(settings.admin_refresh_cookie_name)

    me = auth_client.get("/api/auth/me", headers=bearer(logged_in["token"]))
    assert me.status_code == 200
    assert me.json()["user"]["username"] == "admin"

    refreshed = auth_client.post("/api/auth/refresh?role=admin")
    assert refreshed.status_code == 200
    assert refreshed.json()["token"] != logged_in["token"]

    logged_out = auth_client.post("/api/auth/logout?role=admin")
    assert logged_out.status_code == 200
    assert auth_client.cookies.get(settings.admin_refresh_cookie_name) is None
    assert auth_client.post("/api/auth/refresh?role=admin").status_code == 401


def test_admin_and_agent_refresh_sessions_coexist(auth_client: TestClient):
    admin = login(auth_client, "admin")
    admin_cookie = auth_client.cookies.get(settings.admin_refresh_cookie_name)
    agent = login(auth_client, "agent")

    assert admin["user"]["role"] == "admin"
    assert agent["user"]["role"] == "agent"
    assert admin_cookie
    assert auth_client.cookies.get(settings.admin_refresh_cookie_name) == admin_cookie
    assert auth_client.cookies.get(settings.agent_refresh_cookie_name)

    refreshed_admin = auth_client.post("/api/auth/refresh?role=admin")
    refreshed_agent = auth_client.post("/api/auth/refresh?role=agent")
    assert refreshed_admin.status_code == 200
    assert refreshed_admin.json()["user"]["role"] == "admin"
    assert refreshed_agent.status_code == 200
    assert refreshed_agent.json()["user"]["role"] == "agent"

    assert auth_client.post("/api/auth/logout?role=admin").status_code == 200
    assert auth_client.cookies.get(settings.admin_refresh_cookie_name) is None
    assert auth_client.cookies.get(settings.agent_refresh_cookie_name)
    assert auth_client.post("/api/auth/refresh?role=agent").status_code == 200


def test_refresh_rejects_cookie_from_another_role(auth_client: TestClient):
    login(auth_client, "admin")
    admin_cookie = auth_client.cookies.get(settings.admin_refresh_cookie_name)
    auth_client.cookies.set(settings.agent_refresh_cookie_name, admin_cookie)

    response = auth_client.post("/api/auth/refresh?role=agent")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_ROLE_MISMATCH"


def test_login_clears_legacy_shared_cookie(auth_client: TestClient):
    auth_client.cookies.set(
        settings.refresh_cookie_name,
        "legacy-token",
        domain="testserver.local",
        path="/api/auth",
    )

    login(auth_client, "admin")

    assert auth_client.cookies.get(settings.refresh_cookie_name) is None


def test_initialized_agent_without_managed_credentials_is_unavailable(
    auth_client: TestClient, monkeypatch
):
    monkeypatch.setattr(
        passwords.config_manager,
        "get",
        lambda key, default=None: True if key == "setup.initialized" else default,
    )

    response = auth_client.post(
        "/api/auth/login",
        json={"username": "agent", "password": "agent-password", "role": "agent"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AGENT_CREDENTIALS_NOT_CONFIGURED"


def test_agent_and_admin_role_matrix(auth_client: TestClient):
    agent_token = login(auth_client, "agent")["token"]
    assert auth_client.get("/agent-only", headers=bearer(agent_token)).status_code == 200
    assert auth_client.get("/admin-only", headers=bearer(agent_token)).status_code == 403

    admin_token = login(auth_client, "admin")["token"]
    assert auth_client.get("/agent-only", headers=bearer(admin_token)).status_code == 200
    assert auth_client.get("/admin-only", headers=bearer(admin_token)).status_code == 200


def test_missing_and_invalid_tokens_are_401(auth_client: TestClient):
    assert auth_client.get("/agent-only").status_code == 401
    response = auth_client.get(
        "/agent-only",
        headers={"Authorization": "Bearer invalid"},
    )
    assert response.status_code == 401


def test_refresh_origin_is_checked(auth_client: TestClient):
    login(auth_client, "admin")
    response = auth_client.post(
        "/api/auth/refresh?role=admin",
        headers={"Origin": "https://attacker.example"},
    )
    assert response.status_code == 403
