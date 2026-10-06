from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src import main
from src.services.dify import AIResponse
from src.utils.metrics import normalize_handoff_reason, normalize_webhook_event


@pytest.mark.asyncio
async def test_local_provider_never_silently_falls_back_to_dify(monkeypatch):
    dify = SimpleNamespace(chat=AsyncMock())
    monkeypatch.setattr(main.settings, "ai_provider", "local")
    monkeypatch.setattr(main, "ai_engine", None)
    monkeypatch.setattr(main, "dify", dify, raising=False)

    with pytest.raises(RuntimeError, match="not initialized"):
        await main.request_ai_response("hello", "user", "conversation")

    dify.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_dify_provider_is_explicit(monkeypatch):
    response = AIResponse(text="ok", confidence=0.9, metadata={})
    dify = SimpleNamespace(chat=AsyncMock(return_value=response))
    monkeypatch.setattr(main.settings, "ai_provider", "dify")
    monkeypatch.setattr(main, "dify", dify, raising=False)

    result = await main.request_ai_response("hello", "user", "conversation")

    assert result is response
    dify.chat.assert_awaited_once()


def test_metric_labels_are_bounded():
    assert normalize_handoff_reason("AI 置信度过低: 0.12") == "low_confidence"
    assert normalize_handoff_reason("连续 3 次未能解决问题") == "unresolved"
    assert normalize_handoff_reason("arbitrary customer text 123") == "other"
    assert normalize_webhook_event("tenant-custom-event-42") == "other"
