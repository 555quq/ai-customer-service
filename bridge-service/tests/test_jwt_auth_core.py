"""Unit tests for JWT, password, and refresh-session primitives."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from src.auth.models import AuthUser
from src.auth.passwords import authenticate_configured_user, hash_password
from src.auth.passwords import AgentCredentialsNotConfigured
from src.auth.session_store import (
    AuthSessionStore,
    RefreshReuseDetected,
    RefreshSession,
    hash_refresh_token,
)
from src.auth.tokens import (
    AuthConfigurationError,
    TokenValidationError,
    create_access_token,
    create_refresh_token,
    create_widget_token,
    create_widget_session_token,
    decode_token,
    jwt_secret,
    validate_widget_token,
    validate_widget_session_token,
    WidgetScopeError,
)
from src.config import settings
from src.utils.config_manager import config_manager


@pytest.fixture(autouse=True)
def auth_settings(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "jwt_secret", "test-secret-with-at-least-32-characters")
    monkeypatch.setattr(settings, "jwt_issuer", "test-issuer")
    monkeypatch.setattr(settings, "jwt_audience", "test-audience")
    monkeypatch.setattr(settings, "access_token_minutes", 30)
    monkeypatch.setattr(settings, "refresh_token_days", 7)
    monkeypatch.setattr(settings, "widget_token_hours", 24)


def test_access_token_round_trip_and_type_rejection():
    user = AuthUser(id="agent-1", username="agent", role="agent")
    token, issued = create_access_token(user)

    decoded = decode_token(token, "access")
    assert decoded.sub == "agent-1"
    assert decoded.role == "agent"
    assert decoded.jti == issued.jti
    with pytest.raises(TokenValidationError):
        decode_token(token, "refresh")


def test_refresh_and_widget_tokens_require_bound_claims():
    user = AuthUser(id="admin-1", username="admin", role="admin")
    refresh, _ = create_refresh_token(user, "session-1", "family-1")
    widget, _ = create_widget_token("visitor-1", "42")

    assert decode_token(refresh, "refresh").family_id == "family-1"
    assert decode_token(widget, "widget").chatwoot_conversation_id == "42"
    assert validate_widget_token(widget, "visitor-1", "42").sub == "visitor-1"
    with pytest.raises(WidgetScopeError):
        validate_widget_token(widget, "visitor-2", "42")
    with pytest.raises(WidgetScopeError):
        validate_widget_token(widget, "visitor-1", "43")


def test_widget_session_token_is_bound_to_site_and_conversation():
    token, _ = create_widget_session_token("visitor-conversation", "site-123")
    claims = validate_widget_session_token(token, "visitor-conversation", "site-123")
    assert claims.site_id == "site-123"
    with pytest.raises(WidgetScopeError):
        validate_widget_session_token(token, "another-conversation", "site-123")
    with pytest.raises(WidgetScopeError):
        validate_widget_session_token(token, "visitor-conversation", "site-999")


def test_production_rejects_missing_or_short_jwt_secret(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "jwt_secret", None)
    with pytest.raises(AuthConfigurationError):
        jwt_secret()

    monkeypatch.setattr(settings, "jwt_secret", "too-short")
    with pytest.raises(AuthConfigurationError):
        jwt_secret()


def test_argon2_hash_is_required_in_production(monkeypatch):
    password_hash = hash_password("correct horse battery staple")
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password_hash", password_hash)
    monkeypatch.setattr(settings, "environment", "production")

    assert authenticate_configured_user("admin", "correct horse battery staple", "admin")
    assert authenticate_configured_user("admin", "wrong", "admin") is None

    monkeypatch.setattr(settings, "admin_password_hash", None)
    with pytest.raises(AuthConfigurationError):
        authenticate_configured_user("admin", "anything", "admin")


def test_initialized_deployment_never_uses_plaintext_agent_fallback(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "agent_username", "agent")
    monkeypatch.setattr(settings, "agent_password", "agent-password")
    monkeypatch.setattr(
        config_manager,
        "get",
        lambda key, default=None: True if key == "setup.initialized" else default,
    )

    with pytest.raises(AgentCredentialsNotConfigured):
        authenticate_configured_user("agent", "agent-password", "agent")


def make_session(
    raw_token: str,
    family_id: str = "family-1",
    *,
    user_id: str = "admin-1",
    role: str = "admin",
) -> RefreshSession:
    now = int(datetime.now(timezone.utc).timestamp())
    return RefreshSession(
        jti=str(uuid4()),
        session_id=str(uuid4()),
        family_id=family_id,
        user_id=user_id,
        username=role,
        role=role,
        token_hash=hash_refresh_token(raw_token),
        created_at=now,
        expires_at=now + 3600,
    )


@pytest.mark.asyncio
async def test_refresh_session_is_consumed_once_and_reuse_revokes_family():
    store = AuthSessionStore()
    first = make_session("first-token")
    sibling = make_session("sibling-token", family_id=first.family_id)
    await store.create(first)
    await store.create(sibling)

    consumed = await store.consume(first.jti, "first-token")
    assert consumed.session_id == first.session_id

    with pytest.raises(RefreshReuseDetected):
        await store.consume(first.jti, "first-token")

    assert sibling.jti not in store._sessions


@pytest.mark.asyncio
async def test_refresh_token_hash_mismatch_revokes_family():
    store = AuthSessionStore()
    session = make_session("expected-token")
    await store.create(session)

    with pytest.raises(RefreshReuseDetected):
        await store.consume(session.jti, "different-token")
    assert session.jti not in store._sessions


@pytest.mark.asyncio
async def test_revoke_identity_removes_only_matching_refresh_families():
    store = AuthSessionStore()
    first_agent = make_session(
        "agent-token-1", "agent-family-1", user_id="configured-agent", role="agent"
    )
    second_agent = make_session(
        "agent-token-2", "agent-family-2", user_id="configured-agent", role="agent"
    )
    admin = make_session(
        "admin-token", "admin-family", user_id="configured-admin", role="admin"
    )
    await store.create(first_agent)
    await store.create(second_agent)
    await store.create(admin)

    await store.revoke_identity("agent", "configured-agent")

    assert first_agent.jti not in store._sessions
    assert second_agent.jti not in store._sessions
    assert admin.jti in store._sessions
