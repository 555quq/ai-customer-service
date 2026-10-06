"""API and Chatwoot webhook authentication helpers."""
import hashlib
import hmac
import secrets
import time
import re
from typing import Optional
from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader
from loguru import logger

from ..config import settings

# API Key Header
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_DEV_API_TOKEN = secrets.token_urlsafe(32)


def is_production() -> bool:
    """Return whether security settings should use production requirements."""
    return str(getattr(settings, "environment", "development")).lower() in {
        "production",
        "prod",
    }


def configured_api_keys() -> list[str]:
    """Return configured API keys with surrounding whitespace and blanks removed."""
    raw_keys = getattr(settings, "api_keys", None)
    if isinstance(raw_keys, str):
        return [key.strip() for key in raw_keys.split(",") if key.strip()]
    if raw_keys:
        return [str(key).strip() for key in raw_keys if str(key).strip()]
    return []


def get_login_token() -> str:
    """Return the configured API key or an ephemeral development token.

    Login tokens are the values accepted by the X-API-Key protected routes.
    Production refuses to issue a token when API_KEYS is not configured.
    """
    keys = configured_api_keys()
    if keys:
        return keys[0]
    if is_production():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key authentication is not configured",
        )
    return _DEV_API_TOKEN


async def verify_api_key(api_key: Optional[str] = Security(api_key_header)) -> str:
    """
    验证API Key

    Args:
        api_key: 从请求头获取的API Key

    Returns:
        验证通过的API Key

    Raises:
        HTTPException: API Key无效或缺失
    """
    valid_keys = configured_api_keys()
    if not valid_keys:
        if is_production():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API key authentication is not configured",
            )
        logger.debug("API Key validation is disabled in development mode")
        return "dev_mode"

    # 检查是否提供了API Key
    if not api_key:
        logger.warning("请求缺少API Key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key. Please provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if not any(hmac.compare_digest(api_key, valid_key) for valid_key in valid_keys):
        logger.warning("Invalid API Key")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )

    logger.debug("API Key validation succeeded")
    return api_key


def _timestamp_is_fresh(timestamp: str, tolerance_seconds: int) -> bool:
    """Validate a Chatwoot Unix timestamp against the configured replay window."""
    try:
        timestamp_value = int(timestamp.strip())
    except (AttributeError, TypeError, ValueError):
        return False

    if timestamp_value < 0 or tolerance_seconds < 0:
        return False
    return abs(time.time() - timestamp_value) <= tolerance_seconds


async def verify_webhook_signature(
    signature: Optional[str],
    payload: bytes,
    timestamp: Optional[str] = None,
    version: Optional[str] = None,
    event_id: Optional[str] = None,
) -> bool:
    """
    Validate a Chatwoot webhook signature.

    Version 2 binds the timestamp, stable event ID, and exact raw request body
    into one HMAC. Production accepts only v2. Legacy body-only signatures are
    available solely in development when explicitly enabled.

    Args:
        signature: X-Chatwoot-Signature header
        payload: exact raw request body bytes
        timestamp: X-Chatwoot-Timestamp header
        version: X-Chatwoot-Signature-Version header
        event_id: X-Chatwoot-Event-Id header

    Returns:
        签名是否有效
    """
    secret = str(getattr(settings, "chatwoot_webhook_secret", "") or "").strip()
    if not secret:
        return (
            not is_production()
            and not signature
            and not timestamp
            and not version
            and not event_id
        )

    if not signature:
        return False

    candidate = signature.strip()
    if candidate.startswith("sha256="):
        candidate = candidate[7:]
    if len(candidate) != hashlib.sha256().digest_size * 2:
        return False

    try:
        bytes.fromhex(candidate)
    except ValueError:
        return False

    if version == "v2":
        if timestamp is None or not _timestamp_is_fresh(
            timestamp,
            int(getattr(settings, "webhook_timestamp_tolerance_seconds", 300)),
        ):
            return False
        if not event_id or re.fullmatch(r"[0-9a-f]{64}", event_id) is None:
            return False
        canonical = (
            timestamp.encode("ascii")
            + b"\n"
            + event_id.encode("ascii")
            + b"\n"
            + payload
        )
        expected = hmac.new(
            secret.encode("utf-8"), canonical, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(candidate.lower(), expected)

    if is_production() or not bool(
        getattr(settings, "webhook_allow_legacy_v1", False)
    ):
        return False
    if version not in (None, "v1") or event_id is not None:
        return False

    require_timestamp = bool(getattr(settings, "webhook_require_timestamp", True))
    if timestamp is None:
        if require_timestamp:
            return False
    elif not _timestamp_is_fresh(
        timestamp,
        int(getattr(settings, "webhook_timestamp_tolerance_seconds", 300)),
    ):
        return False

    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(candidate.lower(), expected)


def require_api_key(func):
    """
    API Key装饰器（备用）
    使用FastAPI的Depends更优雅，这里保留用于特殊场景
    """
    from functools import wraps

    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 从kwargs中获取api_key参数
        api_key = kwargs.get('api_key')
        await verify_api_key(api_key)
        return await func(*args, **kwargs)

    return wrapper
