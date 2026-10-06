import pytest
from pydantic import ValidationError

from src.config import AdapterSettings


def settings(**overrides):
    values = {
        "CHATWOOT_ADAPTER_INGRESS_TOKEN": "i" * 64,
        "CHATWOOT_WEBHOOK_SECRET": "s" * 64,
    }
    values.update(overrides)
    return AdapterSettings(**values)


def test_concurrency_defaults_are_safe():
    config = settings()
    assert config.concurrency == 8
    assert config.prefetch == 64
    assert config.buffer_limit == 256
    assert config.shutdown_grace_seconds == 30
    assert config.lease_ttl_seconds == 15
    assert config.lease_renew_seconds == 5


@pytest.mark.parametrize(
    "overrides",
    [
        {"WEBHOOK_ADAPTER_CONCURRENCY": 0},
        {"WEBHOOK_ADAPTER_CONCURRENCY": 33},
        {"WEBHOOK_ADAPTER_PREFETCH": 7, "WEBHOOK_ADAPTER_CONCURRENCY": 8},
        {"WEBHOOK_ADAPTER_BUFFER_LIMIT": 63, "WEBHOOK_ADAPTER_PREFETCH": 64},
        {"WEBHOOK_ADAPTER_SHUTDOWN_GRACE_SECONDS": 0},
        {"WEBHOOK_ADAPTER_LEASE_TTL_SECONDS": 10, "WEBHOOK_ADAPTER_LEASE_RENEW_SECONDS": 5},
    ],
)
def test_invalid_concurrency_configuration_is_rejected(overrides):
    with pytest.raises(ValidationError):
        settings(**overrides)
