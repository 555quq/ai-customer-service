"""JWT creation and strict validation helpers."""

from datetime import datetime, timedelta, timezone
import hmac
import secrets
from typing import Any, Optional
from uuid import uuid4

import jwt
from jwt import InvalidTokenError

from ..config import settings
from .models import AuthUser, TokenClaims, TokenType


class AuthConfigurationError(RuntimeError):
    """Raised when authentication is unsafe or incomplete."""


class TokenValidationError(ValueError):
    """Raised when a JWT is invalid for the requested purpose."""


class WidgetScopeError(TokenValidationError):
    """Raised when a valid widget capability is used for another handoff."""


_DEVELOPMENT_JWT_SECRET = secrets.token_urlsafe(48)


def _is_production() -> bool:
    return str(settings.environment).lower() in {"production", "prod"}


def jwt_secret() -> str:
    """Return a configured secret, with an ephemeral development fallback."""
    configured = str(settings.jwt_secret or "").strip()
    if configured:
        if _is_production() and len(configured) < 32:
            raise AuthConfigurationError("JWT_SECRET must be at least 32 characters")
        return configured
    if _is_production():
        raise AuthConfigurationError("JWT_SECRET is required in production")
    return _DEVELOPMENT_JWT_SECRET


def _encode(
    user: AuthUser,
    token_type: TokenType,
    expires_delta: timedelta,
    extra_claims: Optional[dict[str, Any]] = None,
) -> tuple[str, TokenClaims]:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": user.id,
        "username": user.username,
        "role": user.role,
        "type": token_type,
        "jti": str(uuid4()),
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    if extra_claims:
        payload.update(extra_claims)
    token = jwt.encode(payload, jwt_secret(), algorithm="HS256")
    return token, TokenClaims.model_validate(payload)


def create_access_token(user: AuthUser) -> tuple[str, TokenClaims]:
    return _encode(
        user,
        "access",
        timedelta(minutes=max(1, settings.access_token_minutes)),
    )


def create_refresh_token(
    user: AuthUser,
    session_id: str,
    family_id: str,
) -> tuple[str, TokenClaims]:
    return _encode(
        user,
        "refresh",
        timedelta(days=max(1, settings.refresh_token_days)),
        {"session_id": session_id, "family_id": family_id},
    )


def create_widget_token(
    conversation_id: str,
    chatwoot_conversation_id: str,
) -> tuple[str, TokenClaims]:
    user = AuthUser(id=conversation_id, username="widget", role="widget")
    return _encode(
        user,
        "widget",
        timedelta(hours=max(1, settings.widget_token_hours)),
        {
            "conversation_id": conversation_id,
            "chatwoot_conversation_id": chatwoot_conversation_id,
        },
    )


def create_widget_session_token(
    conversation_id: str,
    site_id: str,
) -> tuple[str, TokenClaims]:
    """Create a short-lived capability for a pre-handoff widget session."""
    user = AuthUser(id=conversation_id, username="widget", role="widget")
    return _encode(
        user,
        "widget",
        timedelta(hours=max(1, settings.widget_token_hours)),
        {"conversation_id": conversation_id, "site_id": site_id},
    )


def decode_token(token: str, expected_type: TokenType) -> TokenClaims:
    """Decode a token and require all security-sensitive claims."""
    try:
        payload = jwt.decode(
            token,
            jwt_secret(),
            algorithms=["HS256"],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require": [
                    "sub", "username", "role", "type", "jti",
                    "iat", "exp", "iss", "aud",
                ]
            },
        )
        claims = TokenClaims.model_validate(payload)
    except (InvalidTokenError, ValueError) as exc:
        raise TokenValidationError("Invalid or expired token") from exc

    if claims.type != expected_type:
        raise TokenValidationError("Token type is not valid for this operation")
    if expected_type == "refresh" and (not claims.session_id or not claims.family_id):
        raise TokenValidationError("Refresh token is missing session claims")
    if expected_type == "widget" and not claims.conversation_id:
        raise TokenValidationError("Widget token is missing conversation claims")
    return claims


def validate_widget_token(
    token: str,
    conversation_id: str,
    chatwoot_conversation_id: str,
) -> TokenClaims:
    """Validate that a widget capability is scoped to the requested handoff."""
    claims = decode_token(token, "widget")
    if not hmac.compare_digest(claims.conversation_id or "", conversation_id):
        raise WidgetScopeError("Widget token does not match this conversation")
    if not claims.chatwoot_conversation_id or not hmac.compare_digest(
        claims.chatwoot_conversation_id or "",
        str(chatwoot_conversation_id),
    ):
        raise WidgetScopeError("Widget token does not match this handoff")
    return claims


def validate_widget_session_token(
    token: str,
    conversation_id: str,
    site_id: str,
) -> TokenClaims:
    claims = decode_token(token, "widget")
    if not hmac.compare_digest(claims.conversation_id or "", conversation_id):
        raise WidgetScopeError("Widget token does not match this conversation")
    if not claims.site_id or not hmac.compare_digest(claims.site_id, site_id):
        raise WidgetScopeError("Widget token does not match this site")
    return claims
