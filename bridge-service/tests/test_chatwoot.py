"""ChatwootService 单元测试（mock httpx 客户端）"""
import pytest
from unittest.mock import AsyncMock, MagicMock
import httpx
from src.services.chatwoot import ChatwootService


@pytest.fixture
def service():
    return ChatwootService(
        base_url='http://localhost:3000',
        api_token='test-token',
        account_id='1',
    )


@pytest.mark.asyncio
async def test_send_message_success(service):
    """成功发送消息"""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {'id': 123, 'content': '你好'}
    service.client.post = AsyncMock(return_value=mock_response)

    result = await service.send_message('conv-1', '你好')

    assert result['id'] == 123
    # 验证 URL 和 payload
    url = service.client.post.call_args[0][0]
    assert '/api/v1/accounts/1/conversations/conv-1/messages' in url
    payload = service.client.post.call_args[1]['json']
    assert payload['content'] == '你好'


@pytest.mark.asyncio
async def test_send_message_private(service):
    """私有消息带 private 标记"""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {'id': 1}
    service.client.post = AsyncMock(return_value=mock_response)

    await service.send_message('conv-1', '内部备注', private=True)

    payload = service.client.post.call_args[1]['json']
    assert payload['private'] is True


@pytest.mark.asyncio
async def test_send_message_http_error_raises(service):
    """HTTP 错误时抛出异常"""
    request = httpx.Request('POST', 'http://localhost:3000/api/v1/accounts/1/conversations/conv-1/messages')
    response = httpx.Response(401, request=request)
    error = httpx.HTTPStatusError('Unauthorized', request=request, response=response)
    service.client.post = AsyncMock(side_effect=error)

    with pytest.raises(httpx.HTTPStatusError):
        await service.send_message('conv-1', 'hi')


@pytest.mark.asyncio
async def test_list_conversations_success(service):
    """获取会话列表"""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {'data': [{'id': 1, 'status': 'open'}]}
    service.client.get = AsyncMock(return_value=mock_response)

    result = await service.list_conversations('open')

    assert result['data'][0]['id'] == 1
    # 验证 status 参数
    params = service.client.get.call_args[1]['params']
    assert params['status'] == 'open'


def test_headers_contain_api_access_token():
    """客户端请求头包含 api_access_token"""
    svc = ChatwootService('http://localhost:3000', 'secret-token', '1')
    assert svc.client.headers['api_access_token'] == 'secret-token'


def test_base_url_strips_trailing_slash():
    """base_url 去除末尾斜杠"""
    svc = ChatwootService('http://localhost:3000/', 't', '1')
    assert svc.base_url == 'http://localhost:3000'
