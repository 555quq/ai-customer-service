from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import src.main as main


def test_pytest_runtime_config_is_not_the_live_repository_config():
    live_config = (
        Path(__file__).resolve().parents[1] / "data" / "runtime" / "config.json"
    ).resolve()

    assert main.config_manager.config_file.resolve() != live_config


def _runtime_config():
    return {
        "setup": {"initialized": True},
        "model": {
            "api_base": "https://runtime-model.example/v1",
            "api_key": "runtime-model-secret",
            "model": "runtime-model",
        },
        "chatwoot": {
            "base_url": "https://runtime-chatwoot.example",
            "api_token": "runtime-chatwoot-secret",
            "account_id": "9",
            "inbox_id": 12,
        },
        "ai_rules": {
            "confidence_threshold": 0.83,
            "handoff_keywords": ["真人客服"],
            "system_prompt": "Use only the configured runtime knowledge base.",
        },
    }


def test_lifespan_restores_initialized_runtime_config(monkeypatch):
    runtime = _runtime_config()
    fake_chatwoot = MagicMock()
    fake_chatwoot.close = AsyncMock()
    chatwoot_factory = MagicMock(return_value=fake_chatwoot)
    fake_ai = MagicMock()
    fake_ai.initialize = AsyncMock()
    fake_ai.close = AsyncMock()
    ai_factory = MagicMock(return_value=fake_ai)
    fake_dify = MagicMock()
    fake_dify.close = AsyncMock()
    fake_cache = MagicMock()
    fake_cache.ping = AsyncMock(return_value=False)
    fake_cache.close = AsyncMock()

    monkeypatch.setattr(main.config_manager, "get", lambda key, default=None: key == "setup.initialized")
    monkeypatch.setattr(main.config_manager, "get_all", lambda: runtime)
    monkeypatch.setattr(main, "ChatwootService", chatwoot_factory)
    monkeypatch.setattr(main, "AIEngine", ai_factory)
    monkeypatch.setattr(main, "DifyService", MagicMock(return_value=fake_dify))
    monkeypatch.setattr(main, "RedisCache", MagicMock(return_value=fake_cache))
    monkeypatch.setattr(main.settings, "ai_provider", "local")
    for name in (
        "chatwoot_base_url",
        "chatwoot_api_token",
        "chatwoot_account_id",
        "chatwoot_inbox_id",
        "confidence_threshold",
        "handoff_keywords",
    ):
        monkeypatch.setattr(main.settings, name, getattr(main.settings, name))

    with TestClient(main.app):
        chatwoot_factory.assert_called_once_with(
            base_url="https://runtime-chatwoot.example",
            api_token="runtime-chatwoot-secret",
            account_id="9",
        )
        ai_config = ai_factory.call_args.kwargs["config"]
        assert ai_config.openai_api_base == "https://runtime-model.example/v1"
        assert ai_config.openai_api_key == "runtime-model-secret"
        assert ai_config.openai_model == "runtime-model"
        assert main.settings.chatwoot_inbox_id == 12
        assert main.settings.confidence_threshold == 0.83
        assert main.settings.handoff_keywords == ["真人客服"]


@pytest.mark.asyncio
async def test_runtime_reload_keeps_old_clients_when_replacement_fails(monkeypatch):
    old_chatwoot = MagicMock()
    old_chatwoot.close = AsyncMock()
    old_ai = MagicMock()
    old_ai.close = AsyncMock()
    replacement_chatwoot = MagicMock()
    replacement_chatwoot.close = AsyncMock()

    monkeypatch.setattr(main, "chatwoot", old_chatwoot)
    monkeypatch.setattr(main, "ai_engine", old_ai)
    monkeypatch.setattr(main, "ChatwootService", MagicMock(return_value=replacement_chatwoot))
    monkeypatch.setattr(main, "AIEngine", MagicMock(side_effect=RuntimeError("AI replacement failed")))
    monkeypatch.setattr(main.settings, "ai_provider", "local")

    with pytest.raises(RuntimeError, match="AI replacement failed"):
        await main.reload_runtime_services(_runtime_config())

    assert main.chatwoot is old_chatwoot
    assert main.ai_engine is old_ai
    replacement_chatwoot.close.assert_awaited_once()
    old_chatwoot.close.assert_not_awaited()
    old_ai.close.assert_not_awaited()
