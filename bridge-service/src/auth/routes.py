"""Login, refresh, current-user, and logout endpoints."""

from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from ..config import settings
from .dependencies import get_current_user
from .models import AuthUser
from .passwords import AgentCredentialsNotConfigured, authenticate_configured_user
from .session_store import (
    AuthSessionStore,
    RefreshReuseDetected,
    RefreshSession,
    SessionError,
    hash_refresh_token,
)
from .tokens import (
    AuthConfigurationError,
    TokenValidationError,
    create_access_token,
    create_refresh_token,
    decode_token,
)


router = APIRouter(prefix="/api/auth", tags=["Authentication"])
_session_store = AuthSessionStore()


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    role: Literal["agent", "admin"] = "agent"


def is_production() -> bool:
    return str(settings.environment).lower() in {"production", "prod"}


def configure_session_store(redis_client=None) -> AuthSessionStore:
    """Bind refresh sessions to Redis, or memory in development."""
    global _session_store
    _session_store = AuthSessionStore(
        redis_client=redis_client,
        require_redis=is_production(),
    )
    return _session_store


async def revoke_identity_sessions(role: str, user_id: str) -> None:
    """Revoke every refresh session for a configured identity."""
    await _session_store.revoke_identity(role, user_id)


def _allowed_origins() -> set[str]:
    return {
        origin.strip().rstrip("/")
        for origin in str(settings.auth_allowed_origins or "").split(",")
        if origin.strip()
    }


def _verify_cookie_origin(request: Request) -> None:
    origin = request.headers.get("Origin")
    if origin:
        if origin.rstrip("/") not in _allowed_origins():
            raise HTTPException(status_code=403, detail="Origin is not allowed")
    elif is_production():
        raise HTTPException(status_code=403, detail="Origin header is required")


def _refresh_cookie_name(role: Literal["agent", "admin"]) -> str:
    return (
        settings.admin_refresh_cookie_name
        if role == "admin"
        else settings.agent_refresh_cookie_name
    )


def _set_refresh_cookie(
    response: Response,
    token: str,
    role: Literal["agent", "admin"],
) -> None:
    response.set_cookie(
        key=_refresh_cookie_name(role),
        value=token,
        max_age=max(1, settings.refresh_token_days) * 86400,
        httponly=True,
        secure=is_production() or settings.auth_cookie_secure,
        samesite="lax",
        path="/api/auth",
    )


def _clear_refresh_cookie(
    response: Response,
    role: Literal["agent", "admin"],
) -> None:
    response.delete_cookie(
        key=_refresh_cookie_name(role),
        httponly=True,
        secure=is_production() or settings.auth_cookie_secure,
        samesite="lax",
        path="/api/auth",
    )


def _clear_legacy_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        httponly=True,
        secure=is_production() or settings.auth_cookie_secure,
        samesite="lax",
        path="/api/auth",
    )


async def _issue_login_session(user: AuthUser, response: Response) -> dict:
    session_id = str(uuid4())
    family_id = str(uuid4())
    access_token, _ = create_access_token(user)
    refresh_token, refresh_claims = create_refresh_token(user, session_id, family_id)
    await _session_store.create(
        RefreshSession(
            jti=refresh_claims.jti,
            session_id=session_id,
            family_id=family_id,
            user_id=user.id,
            username=user.username,
            role=user.role,
            token_hash=hash_refresh_token(refresh_token),
            created_at=refresh_claims.iat,
            expires_at=refresh_claims.exp,
        )
    )
    _set_refresh_cookie(response, refresh_token, user.role)
    _clear_legacy_refresh_cookie(response)
    return {
        "token": access_token,
        "user": user.model_dump(),
        "expires_in": max(1, settings.access_token_minutes) * 60,
    }


@router.post("/login")
async def login(payload: LoginRequest, response: Response) -> dict:
    try:
        user = authenticate_configured_user(
            payload.username,
            payload.password,
            payload.role,
        )
        if user is None:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        return await _issue_login_session(user, response)
    except AgentCredentialsNotConfigured as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AGENT_CREDENTIALS_NOT_CONFIGURED"},
        ) from exc
    except AuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured",
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication session storage is unavailable",
        ) from exc


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    role: Literal["agent", "admin"],
) -> dict:
    _verify_cookie_origin(request)
    raw_token = request.cookies.get(_refresh_cookie_name(role))
    if not raw_token:
        raise HTTPException(
            status_code=401,
            detail={"code": "MISSING_REFRESH_TOKEN"},
        )

    try:
        claims = decode_token(raw_token, "refresh")
        if claims.role != role:
            _clear_refresh_cookie(response, role)
            raise HTTPException(
                status_code=401,
                detail={"code": "AUTH_ROLE_MISMATCH"},
            )
        session = await _session_store.consume(claims.jti, raw_token)
        if session.role != role:
            _clear_refresh_cookie(response, role)
            raise HTTPException(
                status_code=401,
                detail={"code": "AUTH_ROLE_MISMATCH"},
            )
        user = AuthUser(
            id=session.user_id,
            username=session.username,
            role=session.role,
        )
        access_token, _ = create_access_token(user)
        new_refresh, new_claims = create_refresh_token(
            user,
            session.session_id,
            session.family_id,
        )
        await _session_store.create(
            RefreshSession(
                jti=new_claims.jti,
                session_id=session.session_id,
                family_id=session.family_id,
                user_id=user.id,
                username=user.username,
                role=user.role,
                token_hash=hash_refresh_token(new_refresh),
                created_at=new_claims.iat,
                expires_at=new_claims.exp,
            )
        )
        _set_refresh_cookie(response, new_refresh, role)
        _clear_legacy_refresh_cookie(response)
        return {
            "token": access_token,
            "user": user.model_dump(),
            "expires_in": max(1, settings.access_token_minutes) * 60,
        }
    except RefreshReuseDetected as exc:
        _clear_refresh_cookie(response, role)
        raise HTTPException(status_code=401, detail="Refresh token reuse detected") from exc
    except (TokenValidationError, SessionError) as exc:
        _clear_refresh_cookie(response, role)
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token") from exc
    except (AuthConfigurationError, RuntimeError) as exc:
        raise HTTPException(status_code=503, detail="Authentication is unavailable") from exc


@router.get("/me")
async def me(user: AuthUser = Depends(get_current_user)) -> dict:
    return {"user": user.model_dump()}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    role: Literal["agent", "admin"],
) -> dict:
    _verify_cookie_origin(request)
    raw_token = request.cookies.get(_refresh_cookie_name(role))
    if raw_token:
        try:
            claims = decode_token(raw_token, "refresh")
            if claims.role == role and claims.family_id:
                await _session_store.revoke_family(claims.family_id)
        except (AuthConfigurationError, TokenValidationError, SessionError):
            pass
    _clear_refresh_cookie(response, role)
    _clear_legacy_refresh_cookie(response)
    return {"status": "ok"}
