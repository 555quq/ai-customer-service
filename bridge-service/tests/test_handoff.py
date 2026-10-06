"""转人工闭环单元测试（mock chatwoot / cache / 客服在线状态，无需外部服务）"""
import pytest
from unittest.mock import patch, AsyncMock

from src.main import (
    execute_handoff,
    pick_agent_for_handoff,
    auto_assign_waiting_conversations,
)
from src.services.handoff_store import HandoffStoreUnavailable


# ---------------------------------------------------------------
# execute_handoff
# ---------------------------------------------------------------

@pytest.mark.asyncio
@patch('src.main.handoff_store', create=True)
@patch('src.main.pick_agent_for_handoff', new_callable=AsyncMock)
@patch('src.main.chatwoot', create=True)
async def test_execute_handoff_success_assigns_online_agent(
    mock_chatwoot, mock_pick, mock_handoff_store
):
    """成功转人工：创建联系人/会话、补发访客消息、分配在线客服"""
    mock_chatwoot.create_contact = AsyncMock(return_value={"payload": {"contact": {"id": 42}}})
    mock_chatwoot.create_conversation = AsyncMock(return_value={"payload": {"id": 101}})
    mock_chatwoot.send_message = AsyncMock(return_value={})
    mock_chatwoot.create_label = AsyncMock(return_value={})
    mock_chatwoot.set_labels = AsyncMock(return_value={})
    mock_chatwoot.assign_conversation = AsyncMock(return_value={})
    mock_pick.return_value = {"id": 7, "name": "alice", "count": 1}
    mock_handoff_store.save = AsyncMock()

    result = await execute_handoff("我要退货", "user-12345678", "conv-abc")

    assert result["ok"] is True
    assert result["assigned"] is True
    assert result["conversation_id"] == "101"

    # 联系人/会话均被创建
    mock_chatwoot.create_contact.assert_awaited_once()
    mock_chatwoot.create_conversation.assert_awaited_once()
    # 访客原始消息以 incoming 补发，保证归属到访客
    send_kwargs = mock_chatwoot.send_message.call_args.kwargs
    assert send_kwargs["message_type"] == "incoming"
    assert send_kwargs["content"] == "我要退货"
    # 分配到选中的在线客服
    mock_chatwoot.assign_conversation.assert_awaited_once_with("101", assignee_id=7)
    # handoff 路由和访客绑定被原子保存，供刷新恢复与后续消息路由。
    mock_handoff_store.save.assert_awaited_once_with(
        "conv-abc",
        "user-12345678",
        "101",
    )


@pytest.mark.asyncio
@patch('src.main.handoff_store', create=True)
@patch('src.main.pick_agent_for_handoff', new_callable=AsyncMock)
@patch('src.main.chatwoot', create=True)
async def test_execute_handoff_queues_when_no_online_agent(
    mock_chatwoot, mock_pick, mock_handoff_store
):
    """无在线客服：转人工排队等待，打 waiting 标签，不分配"""
    mock_chatwoot.create_contact = AsyncMock(return_value={"id": 42})
    mock_chatwoot.create_conversation = AsyncMock(return_value={"id": 101})
    mock_chatwoot.send_message = AsyncMock(return_value={})
    mock_chatwoot.create_label = AsyncMock(return_value={})
    mock_chatwoot.set_labels = AsyncMock(return_value={})
    mock_chatwoot.assign_conversation = AsyncMock(return_value={})
    mock_pick.return_value = None
    mock_handoff_store.save = AsyncMock()

    result = await execute_handoff("转人工", "user-abc", "conv-1")

    assert result["ok"] is True
    assert result["assigned"] is False
    # 排队会话打 needs_human + waiting 标签
    set_labels_calls = mock_chatwoot.set_labels.call_args_list
    assert ["needs_human", "waiting"] in [c.args[1] for c in set_labels_calls]
    mock_chatwoot.assign_conversation.assert_not_awaited()


@pytest.mark.asyncio
@patch('src.main.handoff_store', create=True)
@patch('src.main.pick_agent_for_handoff', new_callable=AsyncMock)
@patch('src.main.chatwoot', create=True)
async def test_execute_handoff_contact_conflict_retries(
    mock_chatwoot, mock_pick, mock_handoff_store
):
    """创建联系人冲突（Chatwoot 500）：追加后缀重试一次后成功"""
    mock_chatwoot.create_contact = AsyncMock(side_effect=[
        RuntimeError("409 conflict"),            # 第一次冲突
        {"payload": {"contact": {"id": 42}}},    # 重试成功
    ])
    mock_chatwoot.create_conversation = AsyncMock(return_value={"id": 101})
    mock_chatwoot.send_message = AsyncMock(return_value={})
    mock_chatwoot.create_label = AsyncMock(return_value={})
    mock_chatwoot.set_labels = AsyncMock(return_value={})
    mock_pick.return_value = {"id": 7, "name": "alice", "count": 0}
    mock_handoff_store.save = AsyncMock()

    result = await execute_handoff("hi", "user-123", "conv-1")

    assert result["ok"] is True
    assert mock_chatwoot.create_contact.call_count == 2


@pytest.mark.asyncio
@patch('src.main.chatwoot', create=True)
async def test_execute_handoff_failure_returns_fallback(mock_chatwoot):
    """转人工整体失败：返回兜底回复，不抛异常"""
    mock_chatwoot.create_contact = AsyncMock(side_effect=RuntimeError("boom"))

    result = await execute_handoff("hi", "user-1", "conv-1")

    assert result["ok"] is False
    assert "稍后再试" in result["reply"]


@pytest.mark.asyncio
@patch('src.main.handoff_store', create=True)
@patch('src.main.pick_agent_for_handoff', new_callable=AsyncMock)
@patch('src.main.chatwoot', create=True)
async def test_execute_handoff_fails_closed_when_state_cannot_be_saved(
    mock_chatwoot,
    mock_pick,
    mock_handoff_store,
):
    mock_chatwoot.create_contact = AsyncMock(return_value={"id": 42})
    mock_chatwoot.create_conversation = AsyncMock(return_value={"id": 101})
    mock_chatwoot.send_message = AsyncMock(return_value={})
    mock_pick.return_value = None
    mock_handoff_store.save = AsyncMock(side_effect=HandoffStoreUnavailable())

    result = await execute_handoff("转人工", "visitor-1", "conversation-1")

    assert result["ok"] is False
    assert "capability_token" not in result


# ---------------------------------------------------------------
# pick_agent_for_handoff（负载均衡选客服）
# ---------------------------------------------------------------

@pytest.mark.asyncio
@patch('src.main._get_agent_status', new_callable=AsyncMock)
@patch('src.main.chatwoot', create=True)
async def test_pick_agent_load_balancing(mock_chatwoot, mock_status):
    """负载均衡：从在线客服中选进行中会话最少的一个"""
    mock_chatwoot.list_agents = AsyncMock(return_value=[
        {"id": 1, "name": "alice", "email": "a@x.com"},
        {"id": 2, "name": "bob", "email": "b@x.com"},
        {"id": 3},  # 无名字 → 跳过
    ])
    mock_status.side_effect = ["online", "online"]
    mock_chatwoot.list_conversations = AsyncMock(return_value={
        "data": {"payload": [
            {"id": 10, "meta": {"assignee": {"id": 2}}},
            {"id": 11, "meta": {"assignee": {"id": 2}}},
        ]}
    })

    result = await pick_agent_for_handoff()

    assert result is not None
    assert result["id"] == 1      # alice 0 个会话 < bob 2 个
    assert result["count"] == 0


@pytest.mark.asyncio
@patch('src.main._get_agent_status', new_callable=AsyncMock)
@patch('src.main.chatwoot', create=True)
async def test_pick_agent_no_online_returns_none(mock_chatwoot, mock_status):
    """无在线客服：返回 None，触发排队"""
    mock_chatwoot.list_agents = AsyncMock(return_value=[
        {"id": 1, "name": "alice", "email": "a@x.com"},
    ])
    mock_status.side_effect = ["offline"]

    result = await pick_agent_for_handoff()

    assert result is None


@pytest.mark.asyncio
@patch('src.main._get_agent_status', new_callable=AsyncMock)
@patch('src.main.chatwoot', create=True)
async def test_pick_agent_handles_api_error(mock_chatwoot, mock_status):
    """Chatwoot 会话统计失败不阻塞：仍能按在线客服选出目标"""
    mock_chatwoot.list_agents = AsyncMock(return_value=[
        {"id": 1, "name": "alice", "email": "a@x.com"},
    ])
    mock_status.side_effect = ["online"]
    mock_chatwoot.list_conversations = AsyncMock(side_effect=RuntimeError("api down"))

    result = await pick_agent_for_handoff()

    assert result is not None
    assert result["id"] == 1


# ---------------------------------------------------------------
# auto_assign_waiting_conversations（客服上线自动接管）
# ---------------------------------------------------------------

@pytest.mark.asyncio
@patch('src.main.chatwoot', create=True)
async def test_auto_assign_only_unassigned_waiting(mock_chatwoot):
    """客服上线：只接管未分配且带 needs_human/waiting 标签的会话，跳过已分配"""
    mock_chatwoot.list_agents = AsyncMock(return_value=[{"id": 9, "name": "alice"}])
    mock_chatwoot.list_conversations = AsyncMock(return_value={
        "data": {"payload": [
            {"id": 1, "labels": ["needs_human"]},                          # 未分配 → 接管
            {"id": 2, "labels": ["waiting"], "meta": {"assignee": {"id": 5}}},  # 已分配 → 跳过
            {"id": 3, "labels": ["needs_human"]},                          # 未分配 → 接管
            {"id": 4, "labels": ["normal"]},                               # 无标签 → 跳过
        ]}
    })
    mock_chatwoot.assign_conversation = AsyncMock(return_value={})

    await auto_assign_waiting_conversations("alice")

    assert mock_chatwoot.assign_conversation.await_count == 2
    assigned_ids = [c.args[0] for c in mock_chatwoot.assign_conversation.await_args_list]
    assert assigned_ids == ["1", "3"]
    assert all(c.kwargs["assignee_id"] == 9 for c in mock_chatwoot.assign_conversation.await_args_list)


@pytest.mark.asyncio
@patch('src.main.chatwoot', create=True)
async def test_auto_assign_caps_at_five(mock_chatwoot):
    """客服上线：一次最多接管 5 个等待会话"""
    mock_chatwoot.list_agents = AsyncMock(return_value=[{"id": 9, "name": "alice"}])
    mock_chatwoot.list_conversations = AsyncMock(return_value={
        "data": {"payload": [
            {"id": i, "labels": ["needs_human"]} for i in range(1, 9)
        ]}
    })
    mock_chatwoot.assign_conversation = AsyncMock(return_value={})

    await auto_assign_waiting_conversations("alice")

    assert mock_chatwoot.assign_conversation.await_count == 5


@pytest.mark.asyncio
@patch('src.main.chatwoot', create=True)
async def test_auto_assign_unknown_agent_noop(mock_chatwoot):
    """客服名不存在：不执行任何分配"""
    mock_chatwoot.list_agents = AsyncMock(return_value=[{"id": 9, "name": "alice"}])
    mock_chatwoot.assign_conversation = AsyncMock(return_value={})

    await auto_assign_waiting_conversations("nobody")

    mock_chatwoot.assign_conversation.assert_not_awaited()
