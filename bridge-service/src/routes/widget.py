"""Public widget bootstrap and administrator embed-code endpoints."""

import hashlib
import hmac
from html import escape
from typing import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth.dependencies import require_admin
from ..auth.tokens import create_widget_session_token, create_widget_token
from ..config import settings
from ..services.handoff_store import (
    HandoffRecord,
    HandoffSessionNotRestorable,
    HandoffStoreUnavailable,
    HandoffVisitorMismatch,
)
from ..utils.config_manager import config_manager


router = APIRouter(prefix="/api/widget", tags=["Widget"])
HandoffResolver = Callable[[str, str], Awaitable[HandoffRecord | None]]


async def _unconfigured_handoff_resolver(
    _conversation_id: str,
    _visitor_id: str,
) -> HandoffRecord | None:
    raise HandoffStoreUnavailable("Handoff resolver is not configured")


_handoff_resolver: HandoffResolver = _unconfigured_handoff_resolver


def set_handoff_resolver(resolver: HandoffResolver) -> None:
    global _handoff_resolver
    _handoff_resolver = resolver


class WidgetSessionRequest(BaseModel):
    conversation_id: str = Field(..., min_length=8, max_length=128)
    visitor_id: str = Field(..., min_length=8, max_length=128)


def widget_site_id() -> str:
    token = str(config_manager.get("widget.site_token", ""))
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]


def allowed_widget_origins() -> set[str]:
    return {
        str(origin).strip().rstrip("/")
        for origin in config_manager.get("allowed_origins", [])
        if str(origin).strip()
    }


def verify_widget_site_request(request: Request, supplied_token: str | None) -> None:
    expected = str(config_manager.get("widget.site_token", ""))
    if not expected:
        raise HTTPException(status_code=503, detail={"code": "WIDGET_NOT_CONFIGURED"})
    if not supplied_token or not hmac.compare_digest(supplied_token, expected):
        raise HTTPException(status_code=401, detail={"code": "INVALID_SITE_TOKEN"})
    origin = (request.headers.get("origin") or "").rstrip("/")
    allowed = allowed_widget_origins()
    if not origin:
        raise HTTPException(status_code=403, detail={"code": "ORIGIN_REQUIRED"})
    if origin not in allowed:
        raise HTTPException(status_code=403, detail={"code": "ORIGIN_NOT_ALLOWED"})


@router.get("/config")
async def widget_config(
    request: Request,
    x_site_token: str | None = Header(None, alias="X-Site-Token"),
) -> dict:
    verify_widget_site_request(request, x_site_token)
    return {
        "brandName": config_manager.get("site.name", "在线客服"),
        "welcomeMessage": config_manager.get("ai_rules.welcome_message", "你好！有什么可以帮到您？"),
        "themeColor": config_manager.get("site.brand_color", "#6366f1"),
        "locale": config_manager.get("site.locale", "zh-CN"),
        "theme": config_manager.get("widget.theme", "light"),
        "position": config_manager.get("widget.position", "right"),
    }


@router.post("/session")
async def create_widget_session(
    payload: WidgetSessionRequest,
    request: Request,
    x_site_token: str | None = Header(None, alias="X-Site-Token"),
) -> dict:
    verify_widget_site_request(request, x_site_token)
    try:
        handoff = await _handoff_resolver(payload.conversation_id, payload.visitor_id)
    except HandoffVisitorMismatch as exc:
        raise HTTPException(
            status_code=403,
            detail={"code": "HANDOFF_VISITOR_MISMATCH"},
        ) from exc
    except HandoffSessionNotRestorable as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "HANDOFF_SESSION_NOT_RESTORABLE"},
        ) from exc
    except HandoffStoreUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "HANDOFF_STORE_UNAVAILABLE"},
        ) from exc

    if handoff is not None:
        token, claims = create_widget_token(
            payload.conversation_id,
            handoff.chatwoot_conversation_id,
        )
        return {
            "capability_token": token,
            "expires_at": claims.exp,
            "handoff": True,
            "chatwoot_conversation_id": handoff.chatwoot_conversation_id,
        }

    token, claims = create_widget_session_token(payload.conversation_id, widget_site_id())
    return {
        "capability_token": token,
        "expires_at": claims.exp,
        "handoff": False,
        "chatwoot_conversation_id": None,
    }


@router.get("/snippet", dependencies=[Depends(require_admin)])
async def widget_snippet(request: Request) -> dict:
    site_token = str(config_manager.get("widget.site_token", ""))
    if not site_token:
        raise HTTPException(status_code=409, detail={"code": "WIDGET_NOT_CONFIGURED"})
    is_production = str(settings.environment).lower() in {"production", "prod"}
    configured_public_base = str(settings.widget_public_base_url or "").strip().rstrip("/")
    if is_production:
        if not configured_public_base:
            raise HTTPException(
                status_code=409,
                detail={"code": "WIDGET_PUBLIC_URL_NOT_CONFIGURED"},
            )
        parsed = urlsplit(configured_public_base)
        expected_host = str(settings.widget_host or "").strip().lower().rstrip(".")
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (parsed.port not in {None, 443})
            or (expected_host and parsed.hostname.lower().rstrip(".") != expected_host)
        ):
            raise HTTPException(
                status_code=500,
                detail={"code": "WIDGET_PUBLIC_URL_INVALID"},
            )
        api_base = configured_public_base
        asset_url = f"{api_base}/assets/widget.js"
    else:
        configured_asset = str(config_manager.get("widget.asset_url", "")).strip()
        api_base = str(config_manager.get("widget.api_base", "")).strip() or str(request.base_url).rstrip("/")
        asset_url = configured_asset or f"{api_base}/assets/widget.js"
    snippet = (
        f'<script src="{escape(asset_url)}" data-api-base="{escape(api_base)}" '
        f'data-site-token="{escape(site_token)}" data-theme="{escape(str(config_manager.get("widget.theme", "light")))}" '
        f'data-locale="{escape(str(config_manager.get("site.locale", "zh-CN")))}" defer></script>'
    )
    return {"snippet": snippet, "asset_url": asset_url, "api_base": api_base}
