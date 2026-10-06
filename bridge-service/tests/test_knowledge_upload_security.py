"""Knowledge upload boundary and cleanup tests."""

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from src.config import settings
from src.routes import ai_management


def upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=BytesIO(content))


@pytest.fixture
def upload_engine(tmp_path, monkeypatch):
    loader = MagicMock()
    loader.knowledge_dir = tmp_path / "knowledge"
    loader.load_json.return_value = [
        {"text": "Question: hello\nAnswer: world", "metadata": {"source": "test"}}
    ]
    engine = SimpleNamespace(
        knowledge_loader=loader,
        _index_documents=AsyncMock(),
    )
    monkeypatch.setattr(ai_management, "_ai_engine", engine)
    monkeypatch.setattr(settings, "knowledge_upload_max_bytes", 1024)
    return engine, loader.knowledge_dir


@pytest.mark.asyncio
async def test_upload_discards_client_directories(upload_engine):
    engine, knowledge_dir = upload_engine
    result = await ai_management.upload_knowledge_file(
        upload("..\\..\\outside.json", b'[{"question":"hello","answer":"world"}]')
    )

    assert result["filename"] == "outside.json"
    stored = list(knowledge_dir.iterdir())
    assert len(stored) == 1
    assert stored[0].resolve().is_relative_to(knowledge_dir.resolve())
    engine._index_documents.assert_awaited_once()


@pytest.mark.asyncio
async def test_upload_rejects_oversized_content_and_keeps_no_target(upload_engine):
    _, knowledge_dir = upload_engine
    with pytest.raises(HTTPException) as error:
        await ai_management.upload_knowledge_file(upload("large.json", b"x" * 1025))

    assert error.value.status_code == 413
    assert not knowledge_dir.exists() or not list(knowledge_dir.iterdir())


@pytest.mark.asyncio
async def test_upload_rolls_back_source_file_when_indexing_fails(upload_engine):
    engine, knowledge_dir = upload_engine
    engine._index_documents.side_effect = RuntimeError("qdrant unavailable")

    with pytest.raises(HTTPException) as error:
        await ai_management.upload_knowledge_file(upload("failed.json", b"{}"))

    assert error.value.status_code == 500
    assert not list(knowledge_dir.iterdir())


@pytest.mark.asyncio
async def test_upload_rejects_unsupported_extension(upload_engine):
    with pytest.raises(HTTPException) as error:
        await ai_management.upload_knowledge_file(upload("payload.exe", b"MZ"))
    assert error.value.status_code == 400
