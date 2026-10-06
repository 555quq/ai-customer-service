import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def adapter_settings():
    from src.config import AdapterSettings

    return AdapterSettings(
        CHATWOOT_ADAPTER_INGRESS_TOKEN="i" * 64,
        CHATWOOT_WEBHOOK_SECRET="s" * 64,
        WEBHOOK_ADAPTER_REDIS_URL="redis://redis:6379/0",
    )

