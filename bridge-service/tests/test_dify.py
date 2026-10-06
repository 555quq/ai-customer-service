"""DifyService 单元测试（mock httpx 客户端）"""
import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx
from src.services.dify import DifyService, AIResponse


@pytest.fixture
def service():
    return DifyService(api_url='http://localhost:5001/v1', api_key='test_key_ascii')


@pytest.mark.asyncio
async def test_chat_success(service):
    """成功调用返回 AI 回复"""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        'answer': '您好！',
        'metadata': {'confidence': 0.95},
    }
    service.client.post = AsyncMock(return_value=mock_response)

    result = await service.chat('你好', 'user-1', 'conv-1')

    assert isinstance(result, AIResponse)
    assert result.text == '您好！'
    assert result.confidence == 0.95
    # 验证请求参数
    service.client.post.assert_called_once()
    _, kwargs = service.client.post.call_args
    payload = kwargs['json']
    assert payload['query'] == '你好'
    assert payload['user'] == 'user-1'


@pytest.mark.asyncio
async def test_chat_builds_url_with_v1_suffix(service):
    """URL 以 /v1 结尾时不重复拼接 v1"""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {'answer': 'ok', 'metadata': {}}
    service.client.post = AsyncMock(return_value=mock_response)

    await service.chat('hi', 'u1')
    url = service.client.post.call_args[0][0]
    # api_url 以 /v1 结尾 → 直接追加 /chat-messages
    assert url == 'http://localhost:5001/v1/chat-messages'


@pytest.mark.asyncio
async def test_chat_http_error_returns_fallback(service):
    """HTTP 错误时返回降级回复"""
    request = httpx.Request('POST', 'http://localhost:5001/v1/chat-messages')
    response = httpx.Response(500, request=request)
    error = httpx.HTTPStatusError('Server error', request=request, response=response)
    service.client.post = AsyncMock(side_effect=error)

    result = await service.chat('hi', 'u1')

    assert result.confidence == 0.0
    assert '抱歉' in result.text


@pytest.mark.asyncio
async def test_chat_network_error_returns_fallback(service):
    """网络异常时返回降级回复"""
    service.client.post = AsyncMock(side_effect=httpx.ConnectError('connection failed'))

    result = await service.chat('hi', 'u1')

    assert result.confidence == 0.0
    assert '抱歉' in result.text


def test_invalid_api_key_no_authorization():
    """非 ASCII API Key 不设置 Authorization"""
    svc = DifyService(api_url='http://x', api_key='待配置')
    assert 'Authorization' not in svc.client.headers


def test_valid_api_key_sets_authorization():
    """有效 API Key 设置 Bearer 认证"""
    svc = DifyService(api_url='http://x', api_key='sk-valid-key')
    assert svc.client.headers['Authorization'] == 'Bearer sk-valid-key'
