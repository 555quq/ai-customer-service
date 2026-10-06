"""Environment-backed adapter configuration."""

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AdapterSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    ingress_token: str = Field("", alias="CHATWOOT_ADAPTER_INGRESS_TOKEN")
    webhook_secret: str = Field("", alias="CHATWOOT_WEBHOOK_SECRET")
    redis_url: str = Field("redis://redis:6379/0", alias="WEBHOOK_ADAPTER_REDIS_URL")
    redis_password: str | None = Field(None, alias="WEBHOOK_ADAPTER_REDIS_PASSWORD")
    bridge_url: str = Field(
        "http://bridge:8000/webhook/chatwoot",
        alias="CHATWOOT_ADAPTER_BRIDGE_URL",
    )
    max_body_bytes: int = Field(1_048_576, alias="CHATWOOT_ADAPTER_MAX_BODY_BYTES", ge=1)
    max_attempts: int = Field(6, alias="CHATWOOT_ADAPTER_MAX_ATTEMPTS", ge=1, le=20)
    payload_ttl_seconds: int = Field(
        604_800,
        alias="CHATWOOT_ADAPTER_PAYLOAD_TTL_SECONDS",
        ge=60,
    )
    request_timeout_seconds: float = Field(
        330.0,
        alias="CHATWOOT_ADAPTER_REQUEST_TIMEOUT_SECONDS",
        gt=0,
    )
    gateway_port: int = Field(8080, alias="WEBHOOK_ADAPTER_GATEWAY_PORT")
    worker_metrics_port: int = Field(9101, alias="WEBHOOK_ADAPTER_WORKER_METRICS_PORT")
    worker_name: str = Field("worker-1", alias="WEBHOOK_ADAPTER_WORKER_NAME")
    concurrency: int = Field(8, alias="WEBHOOK_ADAPTER_CONCURRENCY", ge=1, le=32)
    prefetch: int = Field(64, alias="WEBHOOK_ADAPTER_PREFETCH", ge=1, le=1024)
    buffer_limit: int = Field(256, alias="WEBHOOK_ADAPTER_BUFFER_LIMIT", ge=1, le=10_000)
    shutdown_grace_seconds: float = Field(
        30.0,
        alias="WEBHOOK_ADAPTER_SHUTDOWN_GRACE_SECONDS",
        ge=1,
        le=300,
    )
    lease_ttl_seconds: float = Field(
        15.0,
        alias="WEBHOOK_ADAPTER_LEASE_TTL_SECONDS",
        ge=3,
        le=300,
    )
    lease_renew_seconds: float = Field(
        5.0,
        alias="WEBHOOK_ADAPTER_LEASE_RENEW_SECONDS",
        ge=0.5,
        le=120,
    )

    stream_name: str = "ai:webhook-adapter:events"
    consumer_group: str = "webhook-workers"
    dead_letter_stream: str = "ai:webhook-adapter:dead-letter"
    heartbeat_key: str = "ai:webhook-adapter:worker-heartbeat"
    lease_key: str = "ai:webhook-adapter:worker-lease"

    @model_validator(mode="after")
    def validate_concurrency_limits(self) -> "AdapterSettings":
        if self.prefetch < self.concurrency:
            raise ValueError("WEBHOOK_ADAPTER_PREFETCH must be at least concurrency")
        if self.buffer_limit < self.prefetch:
            raise ValueError("WEBHOOK_ADAPTER_BUFFER_LIMIT must be at least prefetch")
        if self.lease_ttl_seconds <= self.lease_renew_seconds * 2:
            raise ValueError("Worker lease TTL must be greater than twice the renew interval")
        return self

    def validate_gateway(self) -> None:
        if len(self.ingress_token.encode("utf-8")) < 32:
            raise RuntimeError("CHATWOOT_ADAPTER_INGRESS_TOKEN must be at least 32 bytes")

    def validate_worker(self) -> None:
        if len(self.webhook_secret.encode("utf-8")) < 32:
            raise RuntimeError("CHATWOOT_WEBHOOK_SECRET must be at least 32 bytes")


settings = AdapterSettings()
