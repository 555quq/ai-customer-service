"""One-time deployment initialization service."""

import asyncio
import hmac
import json
import copy
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import HTTPException
from loguru import logger

from ..auth.passwords import hash_password
from ..config import settings
from ..utils.config_manager import ConfigManager, config_manager


class SetupService:
    WEBHOOK_NAME = "AI Customer Service Webhook Adapter"

    def __init__(self, manager: ConfigManager = config_manager) -> None:
        self.manager = manager
        self._lock = asyncio.Lock()
        self._reload_callback = None

    def set_reload_callback(self, callback) -> None:
        self._reload_callback = callback

    def is_initialized(self) -> bool:
        return bool(self.manager.get("setup.initialized", False))

    def status(self) -> dict[str, Any]:
        return {
            "initialized": self.is_initialized(),
            "setup_token_configured": bool(settings.setup_token),
            "config_encryption_configured": self.manager.encryption_configured,
            "agent_credentials_configured": bool(
                self.manager.get("auth.agent.password_hash", "")
            ),
            "version": 2,
        }

    def verify_token(self, supplied: str | None) -> None:
        expected = str(settings.setup_token or "").strip()
        if not expected:
            raise HTTPException(status_code=503, detail={"code": "SETUP_TOKEN_NOT_CONFIGURED"})
        if not supplied or not hmac.compare_digest(supplied, expected):
            raise HTTPException(status_code=401, detail={"code": "INVALID_SETUP_TOKEN"})

    async def _probe_model(self, model: dict[str, Any]) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{model['api_base'].rstrip('/')}/models",
                headers={"Authorization": f"Bearer {model['api_key']}"},
            )
            response.raise_for_status()

    async def _probe_chatwoot(self, chatwoot: dict[str, Any]) -> None:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{chatwoot['base_url'].rstrip('/')}/api/v1/accounts/{chatwoot['account_id']}/inboxes",
                headers={"api_access_token": chatwoot["api_token"]},
            )
            response.raise_for_status()
            payload = response.json()
        inboxes = payload.get("payload", payload if isinstance(payload, list) else [])
        inbox = next(
            (
                item for item in inboxes
                if isinstance(item, dict) and item.get("id") == chatwoot["inbox_id"]
            ),
            None,
        )
        if inbox is None:
            raise HTTPException(status_code=422, detail={"code": "CHATWOOT_INBOX_NOT_FOUND"})
        channel_type = str(
            inbox.get("channel_type")
            or (inbox.get("channel") or {}).get("type")
            or ""
        )
        if channel_type != "Channel::Api":
            raise HTTPException(
                status_code=422,
                detail={"code": "CHATWOOT_API_INBOX_REQUIRED"},
            )

    async def _register_chatwoot_webhook(
        self, chatwoot: dict[str, Any]
    ) -> dict[str, Any]:
        gateway_base = str(settings.chatwoot_adapter_gateway_url or "").strip().rstrip("/")
        ingress_token = str(settings.chatwoot_adapter_ingress_token or "").strip()
        if not gateway_base or not ingress_token:
            raise HTTPException(
                status_code=503,
                detail={"code": "WEBHOOK_ADAPTER_NOT_CONFIGURED"},
            )

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                readiness = await client.get(f"{gateway_base}/ready")
                readiness.raise_for_status()
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504, detail={"code": "WEBHOOK_GATEWAY_TIMEOUT"}
            ) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=503, detail={"code": "WEBHOOK_GATEWAY_UNAVAILABLE"}
            ) from exc

        account_url = (
            f"{chatwoot['base_url'].rstrip('/')}/api/v1/accounts/"
            f"{chatwoot['account_id']}/webhooks"
        )
        headers = {"api_access_token": chatwoot["api_token"]}
        registration = {
            "name": self.WEBHOOK_NAME,
            "url": f"{gateway_base}/webhook/{ingress_token}",
            "subscriptions": ["message_created"],
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(account_url, headers=headers)
                response.raise_for_status()
                listed = response.json()
                webhooks = listed.get("payload", []) if isinstance(listed, dict) else listed
                if isinstance(webhooks, dict):
                    webhooks = webhooks.get("webhooks", [])
                if not isinstance(webhooks, list):
                    raise ValueError("Unexpected Chatwoot webhook list response")
                matches = [
                    item
                    for item in webhooks
                    if isinstance(item, dict) and item.get("name") == self.WEBHOOK_NAME
                ]
                if not matches:
                    matches = [
                        item
                        for item in webhooks
                        if isinstance(item, dict)
                        and not item.get("name")
                        and item.get("url") == registration["url"]
                    ]
                if len(matches) > 1:
                    raise HTTPException(
                        status_code=409,
                        detail={"code": "CHATWOOT_WEBHOOK_NAME_CONFLICT"},
                    )
                if matches:
                    webhook_id = matches[0].get("id")
                    if webhook_id is None:
                        raise ValueError("Chatwoot webhook is missing an ID")
                    response = await client.patch(
                        f"{account_url}/{webhook_id}",
                        headers=headers,
                        json=registration,
                    )
                    action = "updated"
                else:
                    response = await client.post(
                        account_url, headers=headers, json=registration
                    )
                    action = "created"
                response.raise_for_status()
                result = response.json()
        except HTTPException:
            raise
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail={"code": "CHATWOOT_WEBHOOK_REGISTRATION_TIMEOUT"},
            ) from exc
        except httpx.HTTPStatusError as exc:
            code = (
                "CHATWOOT_WEBHOOK_AUTH_FAILED"
                if exc.response.status_code in (401, 403)
                else "CHATWOOT_WEBHOOK_REGISTRATION_FAILED"
            )
            raise HTTPException(status_code=502, detail={"code": code}) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                status_code=502,
                detail={"code": "CHATWOOT_WEBHOOK_REGISTRATION_FAILED"},
            ) from exc

        if isinstance(result, dict) and isinstance(result.get("payload"), dict):
            result = result["payload"].get("webhook", result["payload"])
        if not isinstance(result, dict) or result.get("id") is None:
            raise HTTPException(
                status_code=502,
                detail={"code": "CHATWOOT_WEBHOOK_REGISTRATION_FAILED"},
            )
        return {
            "id": result["id"],
            "name": self.WEBHOOK_NAME,
            "status": action,
        }

    async def initialize(self, payload: dict[str, Any], supplied_token: str | None) -> dict[str, Any]:
        async with self._lock:
            if self.is_initialized():
                raise HTTPException(status_code=409, detail={"code": "SETUP_ALREADY_COMPLETED"})
            self.verify_token(supplied_token)

            if payload.pop("verify_connections", True):
                try:
                    await self._probe_model(payload["model"])
                    await self._probe_chatwoot(payload["chatwoot"])
                except HTTPException:
                    raise
                except httpx.TimeoutException as exc:
                    raise HTTPException(status_code=504, detail={"code": "UPSTREAM_TIMEOUT"}) from exc
                except httpx.HTTPStatusError as exc:
                    code = "UPSTREAM_AUTH_FAILED" if exc.response.status_code in (401, 403) else "UPSTREAM_UNAVAILABLE"
                    raise HTTPException(status_code=502, detail={"code": code}) from exc
                except (httpx.HTTPError, ValueError) as exc:
                    raise HTTPException(status_code=502, detail={"code": "UPSTREAM_UNAVAILABLE"}) from exc

            webhook_registration = await self._register_chatwoot_webhook(payload["chatwoot"])
            payload.setdefault("integrations", {})["chatwoot_webhook"] = webhook_registration

            now = datetime.now(timezone.utc).isoformat()
            admin = payload.pop("admin")
            agent = payload.pop("agent")
            payload["auth"] = {
                "admin": {
                    "username": admin["username"],
                    "password_hash": hash_password(admin["password"]),
                },
                "agent": {
                    "username": agent["username"],
                    "password_hash": hash_password(agent["password"]),
                },
            }
            payload["widget"] = {
                "site_token": secrets.token_urlsafe(24),
                "theme": "light",
                "position": "right",
            }
            payload["setup"] = {"initialized": True, "initialized_at": now, "version": 2}
            previous_config = copy.deepcopy(self.manager.config)
            try:
                self.manager.update(payload)
                if self._reload_callback:
                    await self._reload_callback(payload)
            except Exception as exc:
                self.manager.restore(previous_config)
                raise HTTPException(status_code=500, detail={"code": "SETUP_APPLY_FAILED"}) from exc
            try:
                self._write_audit("setup.initialized", now)
            except OSError as exc:
                # Runtime and persisted configuration are already consistent;
                # surface the audit failure operationally without rolling back live clients.
                logger.error(f"初始化审计写入失败: {exc}")
            return {"initialized": True, "initialized_at": now}

    def _write_audit(self, event: str, timestamp: str) -> None:
        audit_file = Path(self.manager.config_file).parent / "audit.jsonl"
        audit_file.parent.mkdir(parents=True, exist_ok=True)
        with open(audit_file, "a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, "timestamp": timestamp}) + "\n")


setup_service = SetupService()
