from unittest.mock import AsyncMock

from src.auth import passwords
from src.routes import admin as admin_route
from src.utils.config_manager import ConfigManager


def _login_headers(test_client, role="admin"):
    response = test_client.post(
        "/api/auth/login",
        json={
            "username": role,
            "password": f"{role}123" if role == "agent" else "admin123",
            "role": role,
        },
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['token']}"}


def _isolated_credentials(monkeypatch, tmp_path):
    manager = ConfigManager(str(tmp_path / "runtime.json"), encryption_key="22" * 32)
    manager.update({"setup": {"initialized": True, "version": 1}})
    revoke = AsyncMock()
    monkeypatch.setattr(admin_route, "config_manager", manager, raising=False)
    monkeypatch.setattr(admin_route, "revoke_identity_sessions", revoke, raising=False)
    return manager, revoke


def test_admin_can_query_and_set_agent_credentials(test_client, monkeypatch, tmp_path):
    manager, revoke = _isolated_credentials(monkeypatch, tmp_path)
    headers = _login_headers(test_client)

    before = test_client.get("/api/admin/agent-credentials", headers=headers)
    updated = test_client.put(
        "/api/admin/agent-credentials",
        headers=headers,
        json={"username": "support", "password": "a-new-secure-password"},
    )
    after = test_client.get("/api/admin/agent-credentials", headers=headers)

    assert before.status_code == 200
    assert before.json() == {"username": "agent", "configured": False}
    assert updated.status_code == 200
    assert updated.json() == {"username": "support", "configured": True}
    assert after.json() == {"username": "support", "configured": True}
    assert manager.get("auth.agent.password_hash").startswith("$argon2")
    assert "a-new-secure-password" not in manager.config_file.read_text(encoding="utf-8")
    revoke.assert_awaited_once_with("agent", "configured-agent")

    monkeypatch.setattr(passwords, "config_manager", manager)
    old_login = test_client.post(
        "/api/auth/login",
        json={"username": "agent", "password": "agent123", "role": "agent"},
    )
    new_login = test_client.post(
        "/api/auth/login",
        json={
            "username": "support",
            "password": "a-new-secure-password",
            "role": "agent",
        },
    )

    assert old_login.status_code == 401
    assert new_login.status_code == 200


def test_agent_cannot_manage_agent_credentials(test_client, monkeypatch, tmp_path):
    _isolated_credentials(monkeypatch, tmp_path)
    headers = _login_headers(test_client, role="agent")

    response = test_client.put(
        "/api/admin/agent-credentials",
        headers=headers,
        json={"username": "support", "password": "a-new-secure-password"},
    )

    assert response.status_code == 403


def test_agent_credential_revocation_failure_is_explicit(
    test_client, monkeypatch, tmp_path
):
    manager, revoke = _isolated_credentials(monkeypatch, tmp_path)
    revoke.side_effect = RuntimeError("redis unavailable")
    headers = _login_headers(test_client)

    response = test_client.put(
        "/api/admin/agent-credentials",
        headers=headers,
        json={"username": "support", "password": "a-new-secure-password"},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AUTH_SESSION_REVOCATION_FAILED"
    assert manager.get("auth.agent.username") == "support"


def test_agent_credential_persistence_failure_keeps_previous_config(
    test_client, monkeypatch, tmp_path
):
    manager, revoke = _isolated_credentials(monkeypatch, tmp_path)
    manager.update(
        {
            "auth": {
                "agent": {
                    "username": "existing",
                    "password_hash": "$argon2id$existing",
                }
            }
        }
    )
    monkeypatch.setattr(manager, "update", lambda _value: (_ for _ in ()).throw(OSError("disk full")))
    headers = _login_headers(test_client)

    response = test_client.put(
        "/api/admin/agent-credentials",
        headers=headers,
        json={"username": "support", "password": "a-new-secure-password"},
    )

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "AGENT_CREDENTIAL_UPDATE_FAILED"
    assert manager.get("auth.agent.username") == "existing"
    revoke.assert_not_awaited()
