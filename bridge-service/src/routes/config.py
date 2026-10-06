"""配置管理路由"""
import copy
from typing import Any, Awaitable, Callable, Dict, Optional
import time
import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from loguru import logger

from ..auth.dependencies import require_admin
from ..utils.config_manager import config_manager, sanitize_config


router = APIRouter(prefix="/api/config", tags=["Configuration"], dependencies=[Depends(require_admin)])
RuntimeApplyCallback = Callable[[dict[str, Any]], Awaitable[None]]
_runtime_apply_callback: RuntimeApplyCallback | None = None
RUNTIME_CONFIG_ROOTS = {"model", "chatwoot", "ai_rules", "ai", "handoff"}


def set_runtime_apply_callback(callback: RuntimeApplyCallback) -> None:
    global _runtime_apply_callback
    _runtime_apply_callback = callback


async def _apply_runtime_if_needed(normalized_update: dict[str, Any]) -> None:
    if (
        _runtime_apply_callback
        and config_manager.get("setup.initialized", False)
        and RUNTIME_CONFIG_ROOTS.intersection(normalized_update)
    ):
        await _runtime_apply_callback(config_manager.get_all())


class ConfigUpdate(BaseModel):
    """配置更新请求"""
    key: str
    value: Any


class ConfigBatchUpdate(BaseModel):
    """批量配置更新请求"""
    config: Dict[str, Any]


class ModelConnectionRequest(BaseModel):
    api_base: str
    api_key: str
    model: Optional[str] = None


class ChatwootConnectionRequest(BaseModel):
    base_url: str
    api_token: str
    account_id: str
    inbox_id: Optional[int] = None


def _normalized_http_url(value: str, field: str) -> str:
    url = value.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail={"code": "INVALID_URL", "field": field})
    return url


@router.get("")
async def get_config(key: str = None):
    """
    获取配置

    Args:
        key: 配置键，为空则返回所有配置

    Returns:
        配置内容
    """
    try:
        if key:
            value = config_manager.get(key)
            if value is None:
                raise HTTPException(status_code=404, detail=f"Config key not found: {key}")
            return {"key": key, "value": sanitize_config(value, key)}
        else:
            return config_manager.get_public()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("")
async def update_config(update: ConfigUpdate):
    """
    更新配置项

    Args:
        update: 配置更新内容

    Returns:
        更新结果
    """
    try:
        previous = copy.deepcopy(config_manager.config)
        config_manager.set(update.key, update.value)
        normalized = config_manager.normalize_update({update.key: update.value})
        try:
            await _apply_runtime_if_needed(normalized)
        except Exception:
            config_manager.restore(previous)
            raise
        return {
            "status": "success",
            "key": update.key,
            "value": sanitize_config(update.value, update.key)
        }
    except Exception as e:
        logger.error(f"更新配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/test-model")
async def test_model_connection(request: ModelConnectionRequest):
    """Validate an OpenAI-compatible endpoint without persisting credentials."""
    api_base = _normalized_http_url(request.api_base, "api_base")
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{api_base}/models",
                headers={"Authorization": f"Bearer {request.api_key}"},
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail={"code": "MODEL_TIMEOUT"}) from exc
    except httpx.HTTPStatusError as exc:
        code = "MODEL_AUTH_FAILED" if exc.response.status_code in (401, 403) else "MODEL_UNAVAILABLE"
        raise HTTPException(status_code=502, detail={"code": code, "upstream_status": exc.response.status_code}) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail={"code": "MODEL_UNAVAILABLE"}) from exc

    model_ids = [item.get("id") for item in payload.get("data", []) if isinstance(item, dict)]
    return {
        "success": True,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "model_available": not request.model or request.model in model_ids,
        "models": model_ids[:50],
    }


@router.post("/test-chatwoot")
async def test_chatwoot_connection(request: ChatwootConnectionRequest):
    """Validate Chatwoot account/token and optionally the configured inbox."""
    base_url = _normalized_http_url(request.base_url, "base_url")
    started = time.perf_counter()
    url = f"{base_url}/api/v1/accounts/{request.account_id}/inboxes"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers={"api_access_token": request.api_token})
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail={"code": "CHATWOOT_TIMEOUT"}) from exc
    except httpx.HTTPStatusError as exc:
        code = "CHATWOOT_AUTH_FAILED" if exc.response.status_code in (401, 403) else "CHATWOOT_UNAVAILABLE"
        raise HTTPException(status_code=502, detail={"code": code, "upstream_status": exc.response.status_code}) from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail={"code": "CHATWOOT_UNAVAILABLE"}) from exc

    inboxes = payload.get("payload", payload if isinstance(payload, list) else [])
    inbox_ids = [item.get("id") for item in inboxes if isinstance(item, dict)]
    return {
        "success": True,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "inbox_available": request.inbox_id is None or request.inbox_id in inbox_ids,
        "inboxes": [{"id": item.get("id"), "name": item.get("name", "")} for item in inboxes if isinstance(item, dict)],
    }


@router.post("/batch")
async def batch_update_config(update: ConfigBatchUpdate):
    """
    批量更新配置

    Args:
        update: 批量配置内容

    Returns:
        更新结果
    """
    try:
        previous = copy.deepcopy(config_manager.config)
        normalized = config_manager.update(update.config)
        try:
            await _apply_runtime_if_needed(normalized)
        except Exception:
            config_manager.restore(previous)
            raise
        return {
            "status": "success",
            "updated": len(update.config)
        }
    except Exception as e:
        logger.error(f"批量更新配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reload")
async def reload_config():
    """
    重新加载配置

    Returns:
        重载结果
    """
    try:
        config_manager.reload()
        return {
            "status": "success",
            "message": "Configuration reloaded",
            "config": config_manager.get_public()
        }
    except Exception as e:
        logger.error(f"重载配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reset")
async def reset_config():
    """
    重置配置为默认值

    Returns:
        重置结果
    """
    try:
        config_manager.reset()
        return {
            "status": "success",
            "message": "Configuration reset to defaults",
            "config": config_manager.get_public()
        }
    except Exception as e:
        logger.error(f"重置配置失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
