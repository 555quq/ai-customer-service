"""管理后台路由（客户列表等聚合能力）"""
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Depends
from loguru import logger
from pydantic import BaseModel, Field

from ..auth.dependencies import require_admin
from ..auth.passwords import hash_password
from ..auth.routes import revoke_identity_sessions
from ..services.chatwoot import ChatwootService
from ..config import settings
from ..utils.config_manager import config_manager


router = APIRouter(prefix="/api/admin", tags=["Admin"], dependencies=[Depends(require_admin)])


class AgentCredentialUpdate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=12, max_length=256)


@router.get("/agent-credentials")
async def get_agent_credentials() -> dict:
    runtime_agent = config_manager.get("auth.agent", {}) or {}
    return {
        "username": runtime_agent.get("username") or settings.agent_username,
        "configured": bool(runtime_agent.get("password_hash")),
    }


@router.put("/agent-credentials")
async def update_agent_credentials(payload: AgentCredentialUpdate) -> dict:
    try:
        config_manager.update(
            {
                "auth": {
                    "agent": {
                        "username": payload.username,
                        "password_hash": hash_password(payload.password),
                    }
                }
            }
        )
    except Exception as exc:
        logger.error("Agent credential persistence failed")
        raise HTTPException(
            status_code=500,
            detail={"code": "AGENT_CREDENTIAL_UPDATE_FAILED"},
        ) from exc

    try:
        await revoke_identity_sessions("agent", "configured-agent")
    except Exception as exc:
        logger.error("Agent refresh-session revocation failed")
        raise HTTPException(
            status_code=503,
            detail={"code": "AUTH_SESSION_REVOCATION_FAILED"},
        ) from exc

    return {"username": payload.username, "configured": True}


def _map_channel(channel: Optional[str]) -> str:
    """映射 Chatwoot 渠道到前端渠道枚举（与 main.py 保持一致）。"""
    value = (channel or "").lower()
    if "wechat" in value:
        return "wechat"
    if "whatsapp" in value:
        return "whatsapp"
    if "api" in value or "app" in value:
        return "app"
    return "web"


def _ts_to_iso(value: Any) -> str:
    """转换 Chatwoot 时间戳/字符串为 ISO 字符串。"""
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    return str(value)


def _get_sender(conv: dict) -> dict:
    """从会话元数据中提取联系人信息（Chatwoot payload 结构）。"""
    meta = conv.get("meta") or {}
    return meta.get("sender") or meta.get("contact") or {}


@router.get("/contacts")
async def list_contacts() -> dict:
    """
    获取客户列表（从全部会话中按联系人去重聚合）。

    Returns:
        {"contacts": [{"id", "name", "email", "phone", "channel", "lastActive", "conversationCount"}]}
    """
    chatwoot = ChatwootService(
        base_url=settings.chatwoot_base_url,
        api_token=settings.chatwoot_api_token,
        account_id=settings.chatwoot_account_id,
    )
    try:
        conversations = await chatwoot.list_all_conversations(status='all')
        by_id: dict[str, dict] = {}
        for conv in conversations:
            sender = _get_sender(conv)
            cid = str(sender.get("id") or conv.get("contact_id") or conv.get("id"))
            entry = by_id.setdefault(cid, {
                "id": cid,
                "name": sender.get("name") or sender.get("email") or f"访客 {cid}",
                "email": sender.get("email"),
                "phone": sender.get("phone_number"),
                "channel": _map_channel(meta_channel(conv, sender)),
                "lastActive": _ts_to_iso(conv.get("last_activity_at") or conv.get("created_at")),
                "conversationCount": 0,
            })
            entry["conversationCount"] += 1
            ts = conv.get("last_activity_at") or conv.get("created_at")
            if ts and str(ts) > str(entry.get("_lastActiveTs", "")):
                entry["_lastActiveTs"] = str(ts)
                entry["lastActive"] = _ts_to_iso(ts)
        for c in by_id.values():
            c.pop("_lastActiveTs", None)
        contacts = list(by_id.values())
        contacts.sort(key=lambda c: c["conversationCount"], reverse=True)
        return {"contacts": contacts}
    except Exception as e:
        logger.error(f"获取客户列表失败: {e}", exc_info=True)
        raise HTTPException(status_code=502, detail="无法获取 Chatwoot 客户列表")
    finally:
        await chatwoot.close()


def meta_channel(conv: dict, sender: dict) -> Optional[str]:
    """渠道优先级：联系人渠道 > 会话渠道。"""
    return sender.get("channel") or conv.get("channel") or conv.get("inbox") or None
