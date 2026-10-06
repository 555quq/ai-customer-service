"""Persistent, duplicate-safe and incremental knowledge ingestion tests."""

import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.routes import knowledge
from src.services.knowledge_jobs import KnowledgeJobRepository
from src.services.knowledge_loader import KnowledgeLoader


def _engine(root: Path):
    return SimpleNamespace(
        knowledge_loader=KnowledgeLoader(root),
        embedding=SimpleNamespace(embed=AsyncMock(return_value=[0.1, 0.2])),
        vector_store=SimpleNamespace(
            add_documents=AsyncMock(),
            delete_by_metadata=AsyncMock(),
        ),
    )


def _create_job(repository, root: Path, filename: str, content: str):
    path = root / f"{hashlib.sha256(content.encode()).hexdigest()[:8]}_{filename}"
    path.write_text(content, encoding="utf-8")
    return repository.create(
        filename=filename,
        stored_path=path,
        file_hash=hashlib.sha256(content.encode()).hexdigest(),
        source_id=knowledge._source_id(filename),
    )


@pytest.mark.asyncio
async def test_duplicate_content_is_not_indexed_twice(monkeypatch, tmp_path):
    repository = KnowledgeJobRepository(tmp_path / "runtime" / "jobs.json")
    engine = _engine(tmp_path / "knowledge")
    monkeypatch.setattr(knowledge, "_job_repository", repository)
    monkeypatch.setattr(knowledge, "_get_ai_engine", lambda: engine)

    first = _create_job(repository, tmp_path, "faq.txt", "A sufficiently long paragraph for indexing.")
    second = _create_job(repository, tmp_path, "copy.txt", "A sufficiently long paragraph for indexing.")

    await knowledge._process_job(first["id"])
    await knowledge._process_job(second["id"])

    assert engine.vector_store.add_documents.await_count == 1
    duplicate = repository.get(second["id"])
    assert duplicate["status"] == "completed"
    assert duplicate["duplicate_of"] == first["id"]
    assert duplicate["documents_indexed"] == 0


@pytest.mark.asyncio
async def test_modified_source_replaces_only_previous_ingestion(monkeypatch, tmp_path):
    repository = KnowledgeJobRepository(tmp_path / "runtime" / "jobs.json")
    engine = _engine(tmp_path / "knowledge")
    monkeypatch.setattr(knowledge, "_job_repository", repository)
    monkeypatch.setattr(knowledge, "_get_ai_engine", lambda: engine)

    first = _create_job(repository, tmp_path, "faq.txt", "The first version contains useful customer guidance.")
    await knowledge._process_job(first["id"])
    second = _create_job(repository, tmp_path, "FAQ.TXT", "The second version contains updated customer guidance.")
    await knowledge._process_job(second["id"])

    assert engine.vector_store.add_documents.await_count == 2
    engine.vector_store.delete_by_metadata.assert_awaited_once_with(
        "ingestion_id",
        first["ingestion_id"],
    )
    source = repository.source(first["source_id"])
    assert source["ingestion_id"] == second["ingestion_id"]
    assert source["documents"] == 1


@pytest.mark.asyncio
async def test_failed_job_persists_error_and_can_be_processed_again(monkeypatch, tmp_path):
    repository_path = tmp_path / "runtime" / "jobs.json"
    repository = KnowledgeJobRepository(repository_path)
    engine = _engine(tmp_path / "knowledge")
    engine.embedding.embed.side_effect = RuntimeError("embedding unavailable")
    monkeypatch.setattr(knowledge, "_job_repository", repository)
    monkeypatch.setattr(knowledge, "_get_ai_engine", lambda: engine)
    job = _create_job(repository, tmp_path, "faq.txt", "A long enough paragraph that should be indexed later.")

    await knowledge._process_job(job["id"])
    failed = KnowledgeJobRepository(repository_path).get(job["id"])
    assert failed["status"] == "failed"
    assert failed["attempts"] == 1
    assert "embedding unavailable" in failed["error"]

    engine.embedding.embed.side_effect = None
    engine.embedding.embed.return_value = [0.1, 0.2]
    repository.update(job["id"], status="pending", error=None)
    await knowledge._process_job(job["id"])

    completed = KnowledgeJobRepository(repository_path).get(job["id"])
    assert completed["status"] == "completed"
    assert completed["attempts"] == 2
