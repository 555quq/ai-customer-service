"""Bridge Service 功能测试

覆盖核心 API 端点的真实路由/鉴权/限流行为；外部服务（AI 引擎/Chatwoot/Redis）以 mock 注入，
保证测试确定性与离线可运行。认证、API Key 校验走真实 settings。
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import src.main as main
from src.config import settings
from src.auth.tokens import create_widget_token
from src.routes.ai_management import set_ai_engine
from src.services.intent import IntentResult

def auth_headers(client: TestClient, role: str = "admin") -> dict[str, str]:
    """Log in through the real auth route and return a bearer header."""
    response = client.post('/api/auth/login', json={
        'username': getattr(settings, f'{role}_username'),
        'password': getattr(settings, f'{role}_password'),
        'role': role,
    })
    assert response.status_code == 200
    return {'Authorization': f"Bearer {response.json()['token']}"}


@pytest.fixture
def mock_runtime(monkeypatch):
    """在 lifespan 之后替换运行时服务，让受测端点不依赖真实外部服务。"""
    # ---- /api/chat 使用的服务 ----
    ai_engine = AsyncMock()
    ai_engine.chat = AsyncMock(
        return_value=SimpleNamespace(reply="我们的营业时间是周一至周五 9:00-18:00", confidence=0.87)
    )
    monkeypatch.setattr(main, 'ai_engine', ai_engine)

    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock(return_value=None)
    monkeypatch.setattr(main, 'cache', cache)

    handoff_store = AsyncMock()
    handoff_store.get_chatwoot_conversation_id = AsyncMock(return_value=None)
    handoff_store.save = AsyncMock(return_value=None)
    monkeypatch.setattr(main, 'handoff_store', handoff_store)

    intent = MagicMock()
    intent.analyze = MagicMock(
        return_value=IntentResult(intent='question', requires_human=False, reason='常规咨询')
    )
    monkeypatch.setattr(main, 'intent_analyzer', intent)

    chatwoot = AsyncMock()
    chatwoot.create_contact = AsyncMock(return_value={"id": 1001})
    chatwoot.create_conversation = AsyncMock(return_value={"id": 5678})
    chatwoot.send_message = AsyncMock(return_value={"id": 1})
    chatwoot.create_label = AsyncMock(return_value={})
    chatwoot.set_labels = AsyncMock(return_value={})
    chatwoot.assign_conversation = AsyncMock(return_value={})
    monkeypatch.setattr(main, 'chatwoot', chatwoot)
    # 无在线客服 → 走排队(waiting)路径，避免真实负载均衡查询
    monkeypatch.setattr(main, 'pick_agent_for_handoff', AsyncMock(return_value=None))

    # ---- /api/ai/* 使用的引擎（通过 set_ai_engine 注入）----
    engine = MagicMock()
    engine.vector_store.get_collection_info.return_value = {"points_count": 16}
    engine.vector_store.scroll_documents = AsyncMock(return_value={"documents": [], "total": 0})
    engine.config = SimpleNamespace(
        openai_model='deepseek-v4-flash',
        openai_api_base='https://api.deepseek.com/v1',
        top_k_results=3,
        similarity_threshold=0.5,
    )
    engine.reload_knowledge = AsyncMock(return_value=None)
    engine.chat = AsyncMock(
        return_value=SimpleNamespace(reply='测试回复', confidence=0.9, intent='question', sources=[])
    )
    set_ai_engine(engine)

    return SimpleNamespace(
        ai_engine=ai_engine,
        cache=cache,
        handoff_store=handoff_store,
        intent=intent,
        chatwoot=chatwoot,
        engine=engine,
    )


# ==================== 认证 ====================

def test_admin_login_success(test_client: TestClient):
    """管理员登录成功返回 API Token"""
    resp = test_client.post('/api/auth/login', json={
        'username': settings.admin_username,
        'password': settings.admin_password,
        'role': 'admin',
    })
    assert resp.status_code == 200
    body = resp.json()
    assert len(body['token'].split('.')) == 3
    assert body['user']['role'] == 'admin'


def test_agent_login_success(test_client: TestClient):
    """客服登录成功返回 API Token"""
    resp = test_client.post('/api/auth/login', json={
        'username': settings.agent_username,
        'password': settings.agent_password,
        'role': 'agent',
    })
    assert resp.status_code == 200
    assert resp.json()['user']['role'] == 'agent'


def test_login_wrong_password_rejected(test_client: TestClient):
    """错误密码返回 401"""
    resp = test_client.post('/api/auth/login', json={
        'username': settings.admin_username,
        'password': 'wrong-password',
        'role': 'admin',
    })
    assert resp.status_code == 401


def test_login_unknown_role_rejected(test_client: TestClient):
    """未知角色由请求模型白名单拒绝。"""
    resp = test_client.post('/api/auth/login', json={
        'username': settings.admin_username,
        'password': settings.admin_password,
        'role': 'superadmin',
    })
    assert resp.status_code == 422


# ==================== JWT 鉴权 ====================

def test_protected_route_missing_bearer_401(test_client: TestClient):
    """受保护路由缺 Bearer token 返回 401。"""
    resp = test_client.get('/api/ai/stats')
    assert resp.status_code == 401


def test_protected_route_invalid_bearer_401(test_client: TestClient):
    """受保护路由带无效 Bearer token 返回 401。"""
    resp = test_client.get('/api/ai/stats', headers={'Authorization': 'Bearer invalid-token'})
    assert resp.status_code == 401


# ==================== /api/chat ====================

def test_chat_returns_ai_reply(test_client: TestClient, mock_runtime):
    """FAQ 提问返回 AI 引擎的回复/置信度/意图"""
    resp = test_client.post('/api/chat', json={
        'message': '你们的营业时间是几点？',
        'conversation_id': 'func-001',
        'user_id': 'u1',
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body['reply'] == '我们的营业时间是周一至周五 9:00-18:00'
    assert body['confidence'] == 0.87
    assert body['intent'] == 'question'
    assert body['handoff'] is None
    mock_runtime.ai_engine.chat.assert_awaited_once()


def test_chat_empty_message_400(test_client: TestClient):
    """空消息返回 400"""
    resp = test_client.post('/api/chat', json={
        'message': '  ',
        'conversation_id': 'func-002',
        'user_id': 'u2',
    })
    assert resp.status_code == 400


def test_chat_handoff_creates_conversation(test_client: TestClient, mock_runtime):
    """转人工意图触发 execute_handoff，在 Chatwoot 创建会话"""
    mock_runtime.intent.analyze.return_value = IntentResult(
        intent='handoff', requires_human=True, reason='用户提及转人工'
    )
    resp = test_client.post('/api/chat', json={
        'message': '我要转人工',
        'conversation_id': 'func-003',
        'user_id': 'u3',
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body['intent'] == 'handoff'
    assert body['handoff'] is not None
    assert body['handoff']['ok'] is True
    assert str(body['handoff']['conversation_id']) == '5678'
    mock_runtime.chatwoot.create_conversation.assert_awaited_once()


def test_chat_handoff_syncs_history_context(test_client: TestClient, mock_runtime):
    """转人工时把转人工前的 AI 对话历史同步到 Chatwoot 会话，客服可看到上下文"""
    async def fake_get(key):
        if key.startswith('conversation:'):
            return json.dumps([
                {'role': 'user', 'content': '你们的营业时间是什么？'},
                {'role': 'assistant', 'content': '我们的营业时间是周一至周五 9:00-18:00'},
            ])
        return None
    mock_runtime.cache.get.side_effect = fake_get
    mock_runtime.intent.analyze.return_value = IntentResult(
        intent='handoff', requires_human=True, reason='用户提及转人工'
    )

    resp = test_client.post('/api/chat', json={
        'message': '我要转人工',
        'conversation_id': 'func-004',
        'user_id': 'u4',
    })
    assert resp.status_code == 200

    calls = mock_runtime.chatwoot.send_message.call_args_list
    contents = [c.kwargs.get('content') for c in calls]
    types = [c.kwargs.get('message_type') for c in calls]
    privates = [c.kwargs.get('private', False) for c in calls]

    # 历史访客消息 → incoming
    user_idx = contents.index('你们的营业时间是什么？')
    assert types[user_idx] == 'incoming'
    assert privates[user_idx] is False

    # 历史 AI 回复 → outgoing + private（仅客服可见备注）
    ai_reply = '🤖 AI 回复：我们的营业时间是周一至周五 9:00-18:00'
    ai_idx = contents.index(ai_reply)
    assert types[ai_idx] == 'outgoing'
    assert privates[ai_idx] is True

    # 触发消息仍会补发
    assert '我要转人工' in contents


def test_handoff_chat_requires_matching_capability(test_client: TestClient, mock_runtime):
    """已转人工会话不能只凭公开 conversation ID 继续发消息。"""
    mock_runtime.handoff_store.get_chatwoot_conversation_id.return_value = "5678"
    payload = {
        'message': '人工客服您好',
        'conversation_id': 'func-capability',
        'user_id': 'u-capability',
    }

    unauthorized = test_client.post('/api/chat', json=payload)
    assert unauthorized.status_code == 401

    token, _ = create_widget_token('func-capability', '5678')
    authorized = test_client.post(
        '/api/chat',
        json=payload,
        headers={'Authorization': f'Bearer {token}'},
    )
    assert authorized.status_code == 200
    assert authorized.json()['handoff']['conversation_id'] == '5678'


def test_handoff_poll_requires_matching_capability(test_client: TestClient, mock_runtime):
    """转人工消息轮询要求同一会话的能力令牌。"""
    mock_runtime.handoff_store.get_chatwoot_conversation_id.return_value = "5678"
    mock_runtime.chatwoot.get_messages = AsyncMock(return_value={'payload': []})

    unauthorized = test_client.get(
        '/api/chat/handoff',
        params={'conversation_id': 'func-poll'},
    )
    assert unauthorized.status_code == 401

    token, _ = create_widget_token('func-poll', '5678')
    authorized = test_client.get(
        '/api/chat/handoff',
        params={'conversation_id': 'func-poll'},
        headers={'Authorization': f'Bearer {token}'},
    )
    assert authorized.status_code == 200
    assert authorized.json() == {
        'handoff': True,
        'conversation_id': '5678',
        'messages': [],
    }


# ==================== AI 管理接口 ====================

def test_ai_stats_with_admin_token(test_client: TestClient, mock_runtime):
    """AI 统计返回向量库与模型配置"""
    resp = test_client.get('/api/ai/stats', headers=auth_headers(test_client))
    assert resp.status_code == 200
    body = resp.json()
    assert body['totalDocuments'] == 16
    assert body['modelName'] == 'deepseek-v4-flash'
    assert body['vectorDBStatus'] == 'healthy'


def test_ai_knowledge_list(test_client: TestClient, mock_runtime):
    """知识库列表透传向量库滚动结果"""
    resp = test_client.get('/api/ai/knowledge', headers=auth_headers(test_client))
    assert resp.status_code == 200
    body = resp.json()
    assert 'documents' in body
    mock_runtime.engine.vector_store.scroll_documents.assert_awaited_once()


def test_ai_knowledge_reload(test_client: TestClient, mock_runtime):
    """重新加载知识库返回成功与文档数"""
    resp = test_client.post('/api/ai/knowledge/reload', headers=auth_headers(test_client))
    assert resp.status_code == 200
    body = resp.json()
    assert body['success'] is True
    assert body['totalDocuments'] == 16
    mock_runtime.engine.reload_knowledge.assert_awaited_once()


def test_ai_test_chat(test_client: TestClient, mock_runtime):
    """测试对话返回 AI 回复"""
    resp = test_client.post('/api/ai/test', headers=auth_headers(test_client), json={'message': '你好'})
    assert resp.status_code == 200
    body = resp.json()
    assert body['reply'] == '测试回复'
    assert body['confidence'] == 0.9


def test_ai_test_requires_bearer(test_client: TestClient):
    """AI 测试接口缺 Bearer token 返回 401。"""
    resp = test_client.post('/api/ai/test', json={'message': '你好'})
    assert resp.status_code == 401


# ==================== Agent 端点 ====================

def test_update_agent_status_persists(test_client: TestClient, mock_runtime):
    """客服上下线状态写入 Redis 缓存"""
    resp = test_client.put(
        '/api/agent/status',
        headers=auth_headers(test_client, "agent"),
        json={'username': 'agent', 'status': 'online'},
    )
    assert resp.status_code == 200
    mock_runtime.cache.set.assert_awaited()
    assert mock_runtime.cache.set.await_args.args[1] == 'online'


# ==================== Admin 端点 ====================

def test_admin_contacts_aggregates(test_client: TestClient, mock_runtime):
    """客户列表按联系人去重聚合会话数"""
    import src.routes.admin as admin_route

    fake_service = AsyncMock()
    fake_service.list_all_conversations = AsyncMock(return_value=[
        {'id': 1, 'contact_id': 27, 'meta': {'sender': {'name': '王小明', 'email': 'w@x.com'}}, 'created_at': 1750000000},
        {'id': 2, 'contact_id': 27, 'meta': {'sender': {'name': '王小明'}}, 'created_at': 1750000001},
        {'id': 3, 'contact_id': 29, 'meta': {'sender': {'name': 'Lisa'}}, 'created_at': 1750000002},
    ])
    fake_service.close = AsyncMock()
    admin_route.ChatwootService = MagicMock(return_value=fake_service)

    resp = test_client.get('/api/admin/contacts', headers=auth_headers(test_client))
    assert resp.status_code == 200
    contacts = resp.json()['contacts']
    # 王小明(2 会话) 与 Lisa(1 会话) 两名客户，按会话数降序
    assert len(contacts) == 2
    assert contacts[0]['name'] == '王小明'
    assert contacts[0]['conversationCount'] == 2
    assert contacts[1]['name'] == 'Lisa'
    assert contacts[1]['conversationCount'] == 1
