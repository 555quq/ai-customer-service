import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from starlette.datastructures import UploadFile

from src.routes import conversations, knowledge
from src.services.knowledge_jobs import KnowledgeJobRepository
from src.services.knowledge_loader import KnowledgeLoader


def _knowledge_engine(knowledge_dir=None):
    client = MagicMock()
    client.scroll.return_value = ([], None)
    client.retrieve.return_value = []
    vector_store = SimpleNamespace(
        collection_name="customer_service_kb",
        client=client,
        get_collection_info=MagicMock(return_value={"points_count": 0}),
        add_documents=AsyncMock(),
        delete_by_metadata=AsyncMock(),
    )
    return SimpleNamespace(
        embedding=SimpleNamespace(embed=AsyncMock(return_value=[0.1, 0.2])),
        vector_store=vector_store,
        knowledge_loader=KnowledgeLoader(knowledge_dir) if knowledge_dir else None,
    )


@pytest.mark.asyncio
async def test_knowledge_import_list_stats_update_and_delete(monkeypatch, tmp_path):
    engine = _knowledge_engine(tmp_path / "knowledge")
    point = SimpleNamespace(
        id="point-1",
        payload={
            "text": "Question: old\nAnswer: old answer",
            "metadata": {
                "question": "old",
                "answer": "old answer",
                "category": "faq",
                "keywords": ["old"],
                "enabled": True,
            },
        },
    )
    engine.vector_store.client.scroll.return_value = ([point], None)
    engine.vector_store.get_collection_info.return_value = {"points_count": 1}
    engine.vector_store.client.retrieve.return_value = [point]
    monkeypatch.setattr(knowledge, "_get_ai_engine", lambda: engine)
    monkeypatch.setattr(
        knowledge,
        "_job_repository",
        KnowledgeJobRepository(tmp_path / "runtime" / "jobs.json"),
    )

    upload = UploadFile(
        filename="knowledge.json",
        file=BytesIO(
            json.dumps([
                {"question": "new", "answer": "new answer", "category": "faq"},
                {"question": "invalid"},
            ]).encode()
        ),
    )
    imported = await knowledge.import_knowledge(BackgroundTasks(), upload)
    await knowledge._process_job(imported["job"]["id"])
    completed = knowledge._job_repository.get(imported["job"]["id"], public=True)
    assert completed["status"] == "completed"
    assert completed["documents_indexed"] == 2
    stored_path = Path(knowledge._job_repository.get(imported["job"]["id"])["stored_path"])
    assert not stored_path.is_relative_to(Path(engine.knowledge_loader.knowledge_dir).resolve())
    engine.vector_store.add_documents.assert_awaited_once()
    assert engine.vector_store.add_documents.await_args.kwargs["metadata"][0]["source"] == "knowledge.json"

    listed = await knowledge.list_knowledge(page=1, size=10, keyword="old")
    assert listed["total"] == 1
    assert listed["items"][0]["id"] == "point-1"
    stats = await knowledge.get_stats()
    assert {key: stats[key] for key in ("total", "enabled", "disabled", "categories")} == {
        "total": 1,
        "enabled": 1,
        "disabled": 0,
        "categories": {"faq": 1},
    }

    updated = await knowledge.update_knowledge(
        "point-1",
        knowledge.KnowledgeItem(question="updated", answer="updated answer", enabled=False),
    )
    assert updated["id"] == "point-1"
    engine.vector_store.client.upsert.assert_called_once()
    upserted = engine.vector_store.client.upsert.call_args.kwargs["points"][0]
    assert upserted.id == "point-1"
    assert upserted.payload["metadata"]["enabled"] is False

    deleted = await knowledge.delete_knowledge("point-1")
    assert deleted == {"status": "success", "id": "point-1"}
    engine.vector_store.client.delete.assert_called_once_with(
        collection_name="customer_service_kb",
        points_selector=["point-1"],
    )


@pytest.mark.asyncio
async def test_knowledge_requires_initialized_ai_engine(monkeypatch):
    monkeypatch.setattr(knowledge, "_get_ai_engine", lambda: (_ for _ in ()).throw(
        HTTPException(status_code=503, detail="AI engine is not initialized")
    ))

    with pytest.raises(HTTPException) as error:
        await knowledge.list_knowledge()
    assert error.value.status_code == 503


def _chatwoot_service():
    service = AsyncMock()
    service.close = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_conversation_detail_uses_chatwoot_messages(monkeypatch):
    service = _chatwoot_service()
    service.get_conversation.return_value = {
        "id": 42,
        "status": "open",
        "created_at": 1700000000,
        "updated_at": 1700000010,
        "meta": {
            "sender": {"id": 7, "name": "Alice"},
            "assignee": {"name": "Agent A"},
        },
        "labels": [{"title": "priority"}],
    }
    service.get_messages.return_value = {
        "payload": [
            {
                "id": 1,
                "message_type": "incoming",
                "sender": {"type": "contact", "name": "Alice"},
                "content": "Hello",
                "created_at": 1700000001,
            },
            {
                "id": 2,
                "message_type": "outgoing",
                "sender": {"type": "user", "name": "Agent A"},
                "content": "Hi",
                "created_at": 1700000002,
            },
        ]
    }
    monkeypatch.setattr(conversations, "_new_chatwoot", lambda: service)

    result = await conversations.get_conversation("42")
    assert result["id"] == "42"
    assert result["user_id"] == "7"
    assert result["labels"] == ["priority"]
    assert result["assigned_agent"] == "Agent A"
    assert [message["sender_type"] for message in result["messages"]] == ["user", "ai"]
    service.get_conversation.assert_awaited_once_with("42")
    service.get_messages.assert_awaited_once_with("42")
    service.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_conversation_search_filters_real_chatwoot_data(monkeypatch):
    service = _chatwoot_service()
    service.list_all_conversations.return_value = [
        {
            "id": 1,
            "status": "open",
            "created_at": "2026-08-18T10:00:00Z",
            "meta": {"sender": {"id": 7, "name": "Alice"}},
            "last_non_activity_message": {"content": "Need a refund"},
        },
        {
            "id": 2,
            "status": "resolved",
            "created_at": "2026-08-17T10:00:00Z",
            "meta": {"sender": {"id": 8, "name": "Bob"}},
            "last_non_activity_message": {"content": "Thanks"},
        },
    ]
    monkeypatch.setattr(conversations, "_new_chatwoot", lambda: service)

    result = await conversations.search_conversations(
        keyword="refund", user_id="7", status="all", page=1, size=20
    )
    assert result["total"] == 1
    assert result["items"][0]["id"] == "1"
    service.list_all_conversations.assert_awaited_once_with(status="all")
    service.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_conversation_export_returns_real_content(monkeypatch):
    service = _chatwoot_service()
    service.get_conversation.return_value = {
        "id": 42,
        "status": "resolved",
        "created_at": "2026-08-18T10:00:00Z",
        "meta": {"sender": {"id": 7, "name": "Alice"}},
        "messages": [
            {
                "id": 1,
                "message_type": "incoming",
                "sender": {"type": "contact", "name": "Alice"},
                "content": "Hello",
                "created_at": "2026-08-18T10:00:01Z",
            }
        ],
    }
    monkeypatch.setattr(conversations, "_new_chatwoot", lambda: service)

    result = await conversations.export_conversation("42", format="csv")
    assert result["conversation_id"] == "42"
    assert result["content_type"] == "text/csv"
    assert "Hello" in result["content"]
    service.get_messages.assert_not_awaited()
    service.close.assert_awaited_once()
