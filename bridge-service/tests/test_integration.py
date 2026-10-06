"""Bridge Service 集成测试"""
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from src.config import settings
from src.services.dify import AIResponse
from src.services.intent import IntentResult


@pytest.fixture
def legacy_webhook_post(monkeypatch, test_client: TestClient):
    """Post application-flow fixtures with an explicit development v1 signature."""
    secret = "integration-webhook-secret"
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "chatwoot_webhook_secret", secret)
    monkeypatch.setattr(settings, "webhook_allow_legacy_v1", True)
    monkeypatch.setattr(settings, "webhook_require_timestamp", True)

    def post(payload: dict | None = None, raw_body: bytes | None = None):
        body = raw_body or json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        timestamp = str(int(time.time()))
        signature = hmac.new(
            secret.encode("utf-8"), body, hashlib.sha256
        ).hexdigest()
        return test_client.post(
            "/webhook/chatwoot",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Chatwoot-Signature-Version": "v1",
                "X-Chatwoot-Timestamp": timestamp,
                "X-Chatwoot-Signature": signature,
            },
        )

    return post


@pytest.mark.integration
def test_health_check(test_client: TestClient):
    """测试健康检查端点

    验证 GET /health 返回 200 状态码和正确的响应体
    """
    response = test_client.get("/health")

    assert response.status_code == 200
    json_response = response.json()
    assert json_response["status"] in ("healthy", "degraded")
    assert json_response["service"] == "bridge-service"
    assert json_response["version"] == "1.0.0"
    assert "uptime_seconds" in json_response
    assert "dependencies" in json_response
    # 新架构：AI 引擎 + Qdrant + Chatwoot（Dify 已被开源 AI 引擎替代）
    assert "ai_engine" in json_response["dependencies"]
    assert "qdrant" in json_response["dependencies"]
    assert "chatwoot" in json_response["dependencies"]


@pytest.mark.integration
def test_webhook_invalid_payload(legacy_webhook_post):
    """测试 Webhook 接收无效 payload

    验证 POST /webhook/chatwoot 在接收到无效 JSON 数据时返回 422
    """
    # 发送非 JSON 格式的数据
    response = legacy_webhook_post(raw_body="这不是有效的 JSON".encode("utf-8"))

    # FastAPI 会返回 422 Unprocessable Entity
    assert response.status_code == 422


@pytest.mark.integration
def test_webhook_non_incoming_message(
    legacy_webhook_post,
    sample_chatwoot_webhook_payload: dict
):
    """测试 Webhook 处理非 incoming 消息

    验证当 message_type 为 'outgoing' 时，服务返回 200 但忽略处理
    """
    # 修改 payload 为 outgoing 消息（机器人自己的消息）
    payload = sample_chatwoot_webhook_payload.copy()
    payload["message"]["message_type"] = "outgoing"

    response = legacy_webhook_post(payload=payload)

    # 应该返回 200，但标记为 ignored
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["status"] == "ignored"
    assert json_response["reason"] == "outgoing_or_private"


@pytest.mark.integration
def test_webhook_non_message_created_event(
    legacy_webhook_post,
    sample_chatwoot_webhook_payload: dict
):
    """测试 Webhook 处理非 message_created 事件

    验证当 event 不是 'message_created' 时，服务返回 200 但忽略处理
    """
    # 修改为其他事件类型
    payload = sample_chatwoot_webhook_payload.copy()
    payload["event"] = "conversation_updated"

    response = legacy_webhook_post(payload=payload)

    # 应该返回 200，但标记为 ignored
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["status"] == "ignored"
    assert json_response["reason"] == "not_message_created"


@pytest.mark.integration
@patch('src.main.cache')
@patch('src.main.dify')
@patch('src.main.chatwoot')
@patch('src.main.intent_analyzer')
def test_webhook_successful_ai_reply(
    mock_intent: AsyncMock,
    mock_chatwoot: AsyncMock,
    mock_dify: AsyncMock,
    mock_cache: AsyncMock,
    legacy_webhook_post,
    sample_chatwoot_webhook_payload: dict
):
    """测试 Webhook 成功处理并返回 AI 回复

    验证完整流程：接收消息 → 意图识别 → 调用 AI → 发送回复
    """
    # Mock 意图识别：不需要转人工
    mock_intent.analyze.return_value = IntentResult(
        intent='question',
        requires_human=False,
        reason='常规咨询'
    )

    # Mock 缓存：未命中
    mock_cache.get_conversation_state = AsyncMock(return_value=None)
    mock_cache.get_cached_answer = AsyncMock(return_value=None)
    mock_cache.cache_answer = AsyncMock(return_value=None)
    mock_cache.reset_unresolved = AsyncMock(return_value=None)

    # Mock Dify AI：返回高置信度回复
    mock_dify.chat = AsyncMock(return_value=AIResponse(
        text="我们的产品价格为 99 元/月",
        confidence=0.95,
        metadata={}
    ))

    # Mock Chatwoot 发送消息
    mock_chatwoot.send_message = AsyncMock(return_value={"id": 123})

    # 发送 Webhook 请求
    with patch("src.main.settings.ai_provider", "dify"):
        response = legacy_webhook_post(payload=sample_chatwoot_webhook_payload)

    # 验证响应
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # 验证调用了意图识别
    mock_intent.analyze.assert_called_once()
    call_args = mock_intent.analyze.call_args[0]
    assert "咨询产品价格" in call_args[0]

    # 验证调用了 Dify AI
    mock_dify.chat.assert_called_once()

    # 验证发送了回复到 Chatwoot
    mock_chatwoot.send_message.assert_called_once()
    send_call = mock_chatwoot.send_message.call_args
    assert send_call.kwargs['content'] == "我们的产品价格为 99 元/月"
    assert send_call.kwargs['private'] is False


@pytest.mark.integration
@patch('src.main.cache')
@patch('src.main.dify')
@patch('src.main.chatwoot')
@patch('src.main.intent_analyzer')
def test_webhook_low_confidence_handoff(
    mock_intent: AsyncMock,
    mock_chatwoot: AsyncMock,
    mock_dify: AsyncMock,
    mock_cache: AsyncMock,
    legacy_webhook_post,
    sample_chatwoot_webhook_payload: dict
):
    """测试低置信度时转人工

    验证当 AI 置信度低于阈值时，系统自动转人工处理
    """
    # Mock 意图识别：不需要立即转人工
    mock_intent.analyze.return_value = IntentResult(
        intent='question',
        requires_human=False,
        reason='常规咨询'
    )

    # Mock 缓存：未命中
    mock_cache.get_conversation_state = AsyncMock(return_value=None)
    mock_cache.get_cached_answer = AsyncMock(return_value=None)
    mock_cache.increment_unresolved = AsyncMock(return_value=1)
    mock_cache.reset_unresolved = AsyncMock(return_value=None)

    # Mock Dify AI：返回低置信度回复
    mock_dify.chat = AsyncMock(return_value=AIResponse(
        text="抱歉，我不太确定",
        confidence=0.3,  # 低于默认阈值 0.7
        metadata={}
    ))

    # Mock Chatwoot 服务
    mock_chatwoot.send_message = AsyncMock(return_value={"id": 123})
    mock_chatwoot.add_label = AsyncMock(return_value={"labels": ["needs_human"]})
    mock_chatwoot.assign_conversation = AsyncMock(return_value={"assignee_id": None})

    # 发送 Webhook 请求
    with patch("src.main.settings.ai_provider", "dify"):
        response = legacy_webhook_post(payload=sample_chatwoot_webhook_payload)

    # 验证响应
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # 验证添加了转人工标签
    assert mock_chatwoot.add_label.call_count >= 1
    # 获取所有调用的标签参数（可能是位置参数或关键字参数）
    label_calls = []
    for call in mock_chatwoot.add_label.call_args_list:
        if 'label' in call.kwargs:
            label_calls.append(call.kwargs['label'])
        elif len(call.args) >= 2:
            label_calls.append(call.args[1])
    assert 'needs_human' in label_calls

    # 验证分配了会话
    mock_chatwoot.assign_conversation.assert_called_once()


@pytest.mark.integration
@patch('src.main.chatwoot')
@patch('src.main.intent_analyzer')
def test_webhook_direct_handoff_by_intent(
    mock_intent: AsyncMock,
    mock_chatwoot: AsyncMock,
    legacy_webhook_post,
    sample_chatwoot_webhook_payload: dict
):
    """测试意图识别直接转人工

    验证当用户消息包含转人工关键词时，直接转人工而不调用 AI
    """
    # Mock 意图识别：需要立即转人工
    mock_intent.analyze.return_value = IntentResult(
        intent='handoff',
        requires_human=True,
        reason='用户提及关键词：人工客服'
    )

    # Mock Chatwoot 服务
    mock_chatwoot.add_label = AsyncMock(return_value={"labels": ["needs_human"]})
    mock_chatwoot.send_message = AsyncMock(return_value={"id": 123})
    mock_chatwoot.assign_conversation = AsyncMock(return_value={"assignee_id": None})

    # 修改消息内容包含转人工关键词
    payload = sample_chatwoot_webhook_payload.copy()
    payload["message"]["content"] = "我要找人工客服"

    # 发送 Webhook 请求
    response = legacy_webhook_post(payload=payload)

    # 验证响应
    assert response.status_code == 200
    assert response.json()["status"] == "success"

    # 验证添加了转人工标签
    assert mock_chatwoot.add_label.call_count >= 1

    # 验证分配了会话
    mock_chatwoot.assign_conversation.assert_called_once()


@pytest.mark.integration
def test_metrics_endpoint(test_client: TestClient):
    """测试 Prometheus 指标端点

    验证 /metrics 端点可以访问并返回 Prometheus 格式的指标
    """
    response = test_client.get("/metrics")

    # Prometheus 指标端点返回 200
    assert response.status_code == 200

    # 验证返回的是文本格式（Prometheus 指标格式）
    assert "text/plain" in response.headers.get("content-type", "")
    assert "ai_customer_service_http_requests_total" in response.text
    assert "ai_customer_service_ai_requests_total" in response.text
    assert "ai_customer_service_chatwoot_requests_total" in response.text
    assert "ai_customer_service_qdrant_operations_total" in response.text
    assert "ai_customer_service_knowledge_jobs_total" in response.text
