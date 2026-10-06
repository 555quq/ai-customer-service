"""配置管理模块"""
from pathlib import Path
from typing import List, Literal, Optional

from pydantic_settings import BaseSettings


BRIDGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BRIDGE_ROOT.parent


class Settings(BaseSettings):
    """应用配置类"""

    # Chatwoot 配置
    chatwoot_base_url: str = "http://localhost:3000"
    chatwoot_api_token: str = "your_chatwoot_token"
    chatwoot_account_id: str = "1"
    # 访客转人工使用的 API 渠道 inbox ID（在 Chatwoot 后台创建）
    chatwoot_inbox_id: int = 3

    # Dify 配置
    dify_api_url: str = "http://localhost:5001"
    dify_api_key: Optional[str] = None

    # AI 配置
    ai_provider: Literal["local", "dify"] = "local"
    confidence_threshold: float = 0.7
    max_unresolved_count: int = 3  # 连续N次未解决自动转人工

    # 转人工关键词
    handoff_keywords: List[str] = [
        "人工", "转人工", "人工客服", "联系客服",
        "投诉", "退款", "售后", "经理"
    ]

    # Security and authentication configuration.
    environment: str = "development"
    widget_public_base_url: Optional[str] = None
    widget_host: Optional[str] = None
    api_keys: Optional[str] = None
    enable_dev_api_key_compat: bool = False
    chatwoot_webhook_secret: Optional[str] = None
    webhook_require_timestamp: bool = True
    webhook_timestamp_tolerance_seconds: int = 300
    webhook_allow_legacy_v1: bool = False
    webhook_idempotency_lock_seconds: int = 600
    webhook_idempotency_done_seconds: int = 7 * 24 * 60 * 60
    chatwoot_adapter_gateway_url: str = "http://webhook-gateway:8080"
    chatwoot_adapter_ingress_token: Optional[str] = None

    # JWT / refresh session configuration.
    jwt_secret: Optional[str] = None
    jwt_issuer: str = "ai-customer-service-bridge"
    jwt_audience: str = "ai-customer-service-ui"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    widget_token_hours: int = 24
    # refresh_cookie_name is retained only to remove the pre-v1.1 shared cookie.
    refresh_cookie_name: str = "ai_cs_refresh"
    admin_refresh_cookie_name: str = "ai_cs_refresh_admin"
    agent_refresh_cookie_name: str = "ai_cs_refresh_agent"
    auth_cookie_secure: bool = False
    auth_allowed_origins: str = (
        "http://localhost:5174,http://127.0.0.1:5174,"
        "http://localhost:5175,http://127.0.0.1:5175"
    )

    # Login credentials used by /api/auth/login.
    admin_username: str = "admin"
    admin_password: Optional[str] = None
    admin_password_hash: Optional[str] = None
    agent_username: str = "agent"
    agent_password: Optional[str] = None
    agent_password_hash: Optional[str] = None

    # Upload limits.
    knowledge_upload_max_bytes: int = 10 * 1024 * 1024

    # One-time bootstrap credential used only while setup is incomplete.
    setup_token: Optional[str] = None
    # Dedicated 32-byte hex key for authenticated runtime-config encryption.
    config_encryption_key: Optional[str] = None

    # Redis 配置（可选）
    redis_host: Optional[str] = None
    redis_port: int = 6379
    redis_password: Optional[str] = None
    redis_db: int = 0

    class Config:
        env_file = (BRIDGE_ROOT / ".env", PROJECT_ROOT / ".env")
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
