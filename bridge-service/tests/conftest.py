"""Pytest 配置和 Fixtures"""
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# src.main creates the process-wide ConfigManager during import. Point it at a
# test-owned path first so an initialized local deployment can never influence
# or be modified by the test suite.
_TEST_RUNTIME_DIRECTORY = tempfile.TemporaryDirectory(prefix="ai-cs-pytest-")
os.environ["AI_CS_RUNTIME_CONFIG_FILE"] = str(
    Path(_TEST_RUNTIME_DIRECTORY.name) / "runtime" / "config.json"
)

import src.main as main
from src.config import settings
from src.main import app

# Tests opt into explicit development-only credentials. Application defaults
# stay unconfigured so a fresh deployment cannot use a known password.
settings.environment = "development"
settings.admin_username = "admin"
settings.admin_password = "admin123"
settings.admin_password_hash = None
settings.agent_username = "agent"
settings.agent_password = "agent123"
settings.agent_password_hash = None


@pytest.fixture
def test_client(monkeypatch):
    """创建 FastAPI 测试客户端

    Returns:
        TestClient: FastAPI 测试客户端实例
    """
    fake_ai = MagicMock()
    fake_ai.initialize = AsyncMock()
    fake_ai.close = AsyncMock()
    fake_ai.config = SimpleNamespace(qdrant_host="localhost", qdrant_port=6333)
    monkeypatch.setattr(main, "AIEngine", MagicMock(return_value=fake_ai))

    fake_chatwoot = MagicMock()
    fake_chatwoot.close = AsyncMock()
    monkeypatch.setattr(main, "ChatwootService", MagicMock(return_value=fake_chatwoot))

    fake_dify = MagicMock()
    fake_dify.close = AsyncMock()
    monkeypatch.setattr(main, "DifyService", MagicMock(return_value=fake_dify))

    fake_cache = MagicMock()
    fake_cache.ping = AsyncMock(return_value=False)
    fake_cache.close = AsyncMock()
    monkeypatch.setattr(main, "RedisCache", MagicMock(return_value=fake_cache))
    monkeypatch.setattr(main, "probe_dependency", AsyncMock(return_value="unreachable"))

    with TestClient(app) as client:
        yield client


@pytest.fixture
def mock_chatwoot_service():
    """Mock Chatwoot 服务

    Returns:
        AsyncMock: Mock 的 Chatwoot 服务实例
    """
    service = AsyncMock()
    service.send_message = AsyncMock(return_value={"id": 123, "content": "test"})
    service.add_label = AsyncMock(return_value={"labels": ["test"]})
    service.assign_conversation = AsyncMock(return_value={"assignee_id": 1})
    service.close = AsyncMock()
    return service


@pytest.fixture
def mock_dify_service():
    """Mock Dify AI 服务

    Returns:
        AsyncMock: Mock 的 Dify 服务实例
    """
    from src.services.dify import AIResponse

    service = AsyncMock()
    service.chat = AsyncMock(return_value=AIResponse(
        text="这是 AI 的回复",
        confidence=0.95,
        metadata={}
    ))
    service.close = AsyncMock()
    return service


@pytest.fixture
def mock_intent_analyzer():
    """Mock 意图识别服务

    Returns:
        MagicMock: Mock 的意图识别器实例
    """
    from src.services.intent import IntentResult

    analyzer = MagicMock()
    analyzer.analyze = MagicMock(return_value=IntentResult(
        intent='question',
        requires_human=False,
        reason='常规咨询'
    ))
    return analyzer


@pytest.fixture
def sample_chatwoot_webhook_payload():
    """Chatwoot Webhook 示例数据

    Returns:
        dict: Webhook payload
    """
    return {
        "event": "message_created",
        "id": 1,
        "message": {
            "id": 12345,
            "content": "你好，我想咨询产品价格",
            "message_type": "incoming",
            "private": False,
            "sender": {
                "id": 1001,
                "name": "测试用户"
            },
            "created_at": 1234567890
        },
        "conversation": {
            "id": 5678,
            "status": "open"
        }
    }
