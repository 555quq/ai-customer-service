"""Conversation history routes backed by Chatwoot."""

import csv
import io
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel

from ..config import settings
from ..services.chatwoot import ChatwootService
from ..auth.dependencies import require_admin


router = APIRouter(prefix="/api/conversations", tags=["Conversations"], dependencies=[Depends(require_admin)])


class ConversationMessage(BaseModel):
    id: str
    sender_type: str
    sender_name: str
    content: str
    created_at: datetime


class ConversationDetail(BaseModel):
    id: str
    user_id: str
    user_name: str
    status: str
    messages: List[ConversationMessage]
    labels: List[str]
    assigned_agent: Optional[str]
    created_at: datetime
    updated_at: datetime


def _new_chatwoot() -> ChatwootService:
    return ChatwootService(
        base_url=settings.chatwoot_base_url,
        api_token=settings.chatwoot_api_token,
        account_id=settings.chatwoot_account_id,
    )


def _unwrap(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {}
    data = raw.get("data")
    return data if isinstance(data, dict) else raw


def _contact(raw: dict) -> dict:
    meta = raw.get("meta") or {}
    return meta.get("sender") or meta.get("contact") or raw.get("contact") or {}


def _assignee(raw: dict) -> dict:
    meta = raw.get("meta") or {}
    return meta.get("assignee") or raw.get("assignee") or {}


def _labels(raw: dict) -> list[str]:
    labels = raw.get("labels") or (raw.get("meta") or {}).get("labels") or []
    result = []
    for label in labels:
        if isinstance(label, dict):
            value = label.get("title") or label.get("name") or label.get("label")
        else:
            value = label
        if value is not None:
            result.append(str(value))
    return result


def _to_datetime(value: Any, fallback: Optional[datetime] = None) -> datetime:
    if isinstance(value, (int, float)):
        if value > 100000000000:
            value /= 1000
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return fallback or datetime.now(timezone.utc)


def _message_list(raw: Any) -> list[dict]:
    if isinstance(raw, list):
        return [message for message in raw if isinstance(message, dict)]
    if isinstance(raw, dict):
        payload = raw.get("payload") or raw.get("messages") or raw.get("data")
        if isinstance(payload, list):
            return [message for message in payload if isinstance(message, dict)]
    return []


def _message_type(message: dict) -> str:
    if message.get("private"):
        return "system"
    sender = message.get("sender") or {}
    sender_type = str(sender.get("type") or message.get("sender_type") or "").lower()
    message_type = message.get("message_type")
    if sender_type == "contact" or message_type in ("incoming", 0):
        return "user"
    if sender_type in ("user", "agent") or message_type in ("outgoing", 1):
        return "ai"
    return "system"


def _map_message(message: dict, user_name: str) -> dict:
    sender = message.get("sender") or {}
    sender_type = _message_type(message)
    default_name = user_name if sender_type == "user" else "AI Assistant"
    return {
        "id": str(message.get("id", "")),
        "sender_type": sender_type,
        "sender_name": sender.get("name") or sender.get("available_name") or default_name,
        "content": message.get("content") or message.get("processed_message_content") or "",
        "created_at": _to_datetime(message.get("created_at")),
    }


def _map_detail(raw: dict, messages: list[dict], conversation_id: str) -> dict:
    raw = _unwrap(raw)
    contact = _contact(raw)
    assignee = _assignee(raw)
    user_id = contact.get("id") or raw.get("contact_id") or raw.get("user_id") or ""
    user_name = contact.get("name") or contact.get("email") or str(user_id or conversation_id)
    created_at = _to_datetime(raw.get("created_at"))
    updated_at = _to_datetime(
        raw.get("updated_at") or raw.get("last_activity_at"),
        fallback=created_at,
    )
    return {
        "id": str(raw.get("id", conversation_id)),
        "user_id": str(user_id),
        "user_name": user_name,
        "status": raw.get("status") or "open",
        "messages": [_map_message(message, user_name) for message in messages],
        "labels": _labels(raw),
        "assigned_agent": assignee.get("name") or assignee.get("available_name"),
        "created_at": created_at,
        "updated_at": updated_at,
    }


async def _fetch_detail(chatwoot: ChatwootService, conversation_id: str) -> dict:
    raw = _unwrap(await chatwoot.get_conversation(conversation_id))
    messages = _message_list(raw.get("messages"))
    if not messages:
        messages = _message_list(await chatwoot.get_messages(conversation_id))
    return _map_detail(raw, messages, conversation_id)


def _last_message(raw: dict) -> str:
    message = raw.get("last_non_activity_message") or raw.get("last_message") or {}
    if isinstance(message, dict):
        return message.get("content") or message.get("processed_message_content") or ""
    return str(message or "")


def _summary_item(raw: dict) -> dict:
    contact = _contact(raw)
    user_id = contact.get("id") or raw.get("contact_id") or raw.get("user_id") or ""
    return {
        "id": str(raw.get("id", "")),
        "user_id": str(user_id),
        "user_name": contact.get("name") or contact.get("email") or str(user_id),
        "status": raw.get("status") or "open",
        "last_message": _last_message(raw),
        "created_at": _to_datetime(raw.get("created_at")),
    }


def _date_value(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return _to_datetime(value).date()
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail=f"Invalid date: {value}")


def _in_date_range(value: Any, start: Optional[date], end: Optional[date]) -> bool:
    current = _to_datetime(value).date()
    return (start is None or current >= start) and (end is None or current <= end)


def _filtered_conversations(
    conversations: list[dict],
    keyword: Optional[str],
    user_id: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
) -> list[dict]:
    start = _date_value(start_date)
    end = _date_value(end_date)
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="start_date must not be after end_date")
    filtered = []
    for raw in conversations:
        summary = _summary_item(raw)
        if user_id and summary["user_id"] != str(user_id):
            continue
        if keyword:
            searchable = f"{summary['user_name']} {summary['last_message']}".casefold()
            if keyword.casefold() not in searchable:
                continue
        if not _in_date_range(raw.get("created_at"), start, end):
            continue
        filtered.append(raw)
    return filtered


@router.get("/search")
async def search_conversations(
    keyword: Optional[str] = None,
    user_id: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    chatwoot = _new_chatwoot()
    try:
        conversations = await chatwoot.list_all_conversations(status=status or "all")
        conversations = _filtered_conversations(
            conversations, keyword, user_id, start_date, end_date
        )
        start = (page - 1) * size
        items = [_summary_item(raw) for raw in conversations[start:start + size]]
        return {
            "items": items,
            "total": len(conversations),
            "page": page,
            "size": size,
            "pages": (len(conversations) + size - 1) // size,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to search conversations: {exc}")
        raise HTTPException(status_code=502, detail="Unable to query Chatwoot")
    finally:
        await chatwoot.close()


@router.get("/analytics/summary")
async def get_analytics_summary(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    chatwoot = _new_chatwoot()
    try:
        conversations = await chatwoot.list_all_conversations(status="all")
        conversations = _filtered_conversations(
            conversations, None, None, start_date, end_date
        )
        total = len(conversations)
        open_count = sum(1 for item in conversations if item.get("status") == "open")
        pending_count = sum(1 for item in conversations if item.get("status") == "pending")
        resolved_count = sum(1 for item in conversations if item.get("status") == "resolved")
        ai_resolved = sum(
            1
            for item in conversations
            if item.get("status") == "resolved"
            and not {"needs_human", "ai_handoff"}.intersection(_labels(item))
        )
        message_counts = [len(_message_list(item.get("messages"))) for item in conversations]
        return {
            "period": {
                "start": start_date or "",
                "end": end_date or datetime.now().strftime("%Y-%m-%d"),
            },
            "total_conversations": total,
            "open_count": open_count,
            "pending_count": pending_count,
            "resolved_count": resolved_count,
            "ai_resolved": ai_resolved,
            "human_resolved": max(0, resolved_count - ai_resolved),
            "ai_resolution_rate": round(ai_resolved / total, 2) if total else 0.0,
            "avg_messages_per_conversation": round(sum(message_counts) / total, 1) if total else 0.0,
            "customer_satisfaction": 0.0,
            "top_intents": {},
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to get conversation analytics: {exc}")
        raise HTTPException(status_code=502, detail="Unable to query Chatwoot")
    finally:
        await chatwoot.close()


@router.get("/analytics/trend")
async def get_conversation_trend(days: int = Query(7, ge=1, le=90)):
    chatwoot = _new_chatwoot()
    try:
        conversations = await chatwoot.list_all_conversations(status="all")
        today = datetime.now(timezone.utc).date()
        buckets = {}
        for index in range(days - 1, -1, -1):
            current = today - timedelta(days=index)
            buckets[current.isoformat()] = {
                "date": current.isoformat(),
                "open": 0,
                "resolved": 0,
                "total": 0,
            }
        for conversation in conversations:
            day = _to_datetime(conversation.get("created_at")).date().isoformat()
            if day not in buckets:
                continue
            buckets[day]["total"] += 1
            if conversation.get("status") == "open":
                buckets[day]["open"] += 1
            elif conversation.get("status") == "resolved":
                buckets[day]["resolved"] += 1
        return {"points": list(buckets.values()), "period": f"{days}d"}
    except Exception as exc:
        logger.error(f"Failed to get conversation trend: {exc}")
        raise HTTPException(status_code=502, detail="Unable to query Chatwoot")
    finally:
        await chatwoot.close()


@router.get("/{conversation_id}/export")
async def export_conversation(conversation_id: str, format: str = "json"):
    if format not in {"json", "csv", "txt"}:
        raise HTTPException(status_code=400, detail="Invalid format")
    chatwoot = _new_chatwoot()
    try:
        detail = await _fetch_detail(chatwoot, conversation_id)
        if format == "json":
            content = json.dumps(detail, ensure_ascii=False, default=str)
            content_type = "application/json"
        elif format == "csv":
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["message_id", "sender_type", "sender_name", "content", "created_at"])
            for message in detail["messages"]:
                writer.writerow([
                    message["id"],
                    message["sender_type"],
                    message["sender_name"],
                    message["content"],
                    message["created_at"].isoformat(),
                ])
            content = output.getvalue()
            content_type = "text/csv"
        else:
            lines = [
                f"Conversation: {detail['id']}",
                f"User: {detail['user_name']}",
                f"Status: {detail['status']}",
                "",
            ]
            lines.extend(
                f"[{message['created_at'].isoformat()}] {message['sender_name']}: {message['content']}"
                for message in detail["messages"]
            )
            content = "\n".join(lines)
            content_type = "text/plain"
        return {
            "conversation_id": conversation_id,
            "format": format,
            "download_url": f"/api/conversations/{conversation_id}/export?format={format}",
            "content": content,
            "content_type": content_type,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to export conversation {conversation_id}: {exc}")
        raise HTTPException(status_code=502, detail="Unable to query Chatwoot")
    finally:
        await chatwoot.close()


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str):
    chatwoot = _new_chatwoot()
    try:
        return await _fetch_detail(chatwoot, conversation_id)
    except Exception as exc:
        logger.error(f"Failed to get conversation {conversation_id}: {exc}")
        raise HTTPException(status_code=502, detail="Unable to query Chatwoot")
    finally:
        await chatwoot.close()
