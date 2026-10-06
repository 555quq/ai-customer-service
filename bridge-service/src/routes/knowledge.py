"""Knowledge base management and asynchronous incremental ingestion routes."""

import asyncio
import hashlib
import time
import re
from pathlib import Path
from typing import Any, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from loguru import logger
from pydantic import BaseModel
from qdrant_client.models import PointStruct
from uuid import uuid4

from ..auth.dependencies import require_admin
from ..config import BRIDGE_ROOT, settings
from ..services.knowledge_jobs import KnowledgeJobRepository
from ..utils.metrics import (
    knowledge_job_duration_seconds,
    knowledge_jobs_in_progress,
    knowledge_jobs_total,
)
from . import ai_management


router = APIRouter(prefix="/api/knowledge", tags=["Knowledge"], dependencies=[Depends(require_admin)])

ALLOWED_EXTENSIONS = {".json", ".txt", ".md", ".markdown", ".pdf", ".docx"}
_job_repository = KnowledgeJobRepository(BRIDGE_ROOT / "data" / "runtime" / "knowledge_jobs.json")
_ingestion_lock = asyncio.Lock()


class KnowledgeItem(BaseModel):
    id: Optional[str] = None
    question: str
    answer: str
    category: Optional[str] = None
    keywords: Optional[List[str]] = None
    enabled: bool = True


class KnowledgeStats(BaseModel):
    total: int
    enabled: int
    disabled: int
    categories: dict


def _get_ai_engine() -> Any:
    engine = ai_management._ai_engine
    if engine is None:
        raise HTTPException(status_code=503, detail="AI engine is not initialized")
    return engine


def _model_dump(item: KnowledgeItem) -> dict:
    if hasattr(item, "model_dump"):
        return item.model_dump()
    return item.dict()


def _knowledge_text(item: KnowledgeItem) -> str:
    return f"Question: {item.question}\nAnswer: {item.answer}"


def _metadata_for_item(
    item: KnowledgeItem,
    source: str = "",
    existing: Optional[dict] = None,
) -> dict:
    metadata = dict(existing or {})
    values = _model_dump(item)
    values.pop("id", None)
    metadata.update(values)
    if source:
        metadata.setdefault("source", source)
    metadata.setdefault("type", "json")
    return metadata


def _collection_name(engine: Any) -> str:
    return engine.vector_store.collection_name


def _scroll_points(engine: Any) -> list[Any]:
    vector_store = engine.vector_store
    info = vector_store.get_collection_info() or {}
    limit = max(int(info.get("points_count", 0) or 0), 1)
    points, _ = vector_store.client.scroll(
        collection_name=_collection_name(engine),
        limit=limit,
        offset=None,
        with_payload=True,
        with_vectors=False,
    )
    return points or []


def _point_item(point: Any) -> dict:
    payload = point.payload or {}
    metadata = payload.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": str(point.id),
        "question": metadata.get("question") or payload.get("text", ""),
        "answer": metadata.get("answer", ""),
        "category": metadata.get("category"),
        "keywords": metadata.get("keywords"),
        "enabled": metadata.get("enabled", True),
        "source": metadata.get("source", ""),
        "source_id": metadata.get("source_id", ""),
        "type": metadata.get("type", ""),
        "text": payload.get("text", ""),
    }


def _matches(item: dict, category: Optional[str], keyword: Optional[str]) -> bool:
    if category and item.get("category") != category:
        return False
    if keyword:
        searchable = " ".join(
            str(item.get(field) or "")
            for field in ("question", "answer", "category", "keywords")
        )
        if keyword.casefold() not in searchable.casefold():
            return False
    return True


def _safe_filename(value: Optional[str]) -> str:
    filename = Path((value or "").replace("\\", "/")).name
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=400, detail="文件名无效")
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {Path(filename).suffix.lower()}")
    return filename


def _source_id(filename: str) -> str:
    normalized = re.sub(r"\s+", " ", filename.strip().casefold())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _load_documents(engine: Any, file_path: Path) -> list[dict[str, Any]]:
    loader = engine.knowledge_loader
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        documents = loader.load_json(file_path)
    elif suffix in {".txt", ".md", ".markdown"}:
        documents = loader.load_txt(file_path)
    elif suffix == ".pdf":
        documents = loader.load_pdf(file_path)
    elif suffix == ".docx":
        documents = loader.load_docx(file_path)
    else:
        documents = []
    if not documents:
        raise ValueError("文件解析失败或内容为空")
    return documents


async def _process_job_locked(job_id: str) -> None:
    job = _job_repository.get(job_id)
    if job is None:
        return
    started = time.perf_counter()
    terminal_status = "failed"
    knowledge_jobs_in_progress.inc()
    new_ingestion_added = False
    try:
        duplicate = _job_repository.find_completed_hash(job["file_hash"], exclude_id=job_id)
        if duplicate is not None:
            _job_repository.update(
                job_id,
                status="completed",
                progress=100,
                documents_total=duplicate.get("documents_total", 0),
                documents_indexed=0,
                duplicate_of=duplicate["id"],
                error=None,
            )
            terminal_status = "duplicate"
            return

        engine = _get_ai_engine()
        attempts = int(job.get("attempts", 0)) + 1
        _job_repository.update(job_id, status="processing", progress=5, attempts=attempts, error=None)
        documents = _load_documents(engine, Path(job["stored_path"]))
        total = len(documents)
        _job_repository.update(job_id, documents_total=total, progress=10)

        texts: list[str] = []
        embeddings: list[list[float]] = []
        metadata: list[dict[str, Any]] = []
        for index, document in enumerate(documents):
            text = str(document.get("text") or "").strip()
            if not text:
                continue
            values = dict(document.get("metadata") or {})
            values.update({
                "source": job["filename"],
                "source_id": job["source_id"],
                "source_hash": job["file_hash"],
                "ingestion_id": job["ingestion_id"],
                "chunk_id": values.get("chunk_id", index),
            })
            texts.append(text)
            metadata.append(values)
            embeddings.append(await engine.embedding.embed(text))
            _job_repository.update(job_id, progress=10 + int(65 * (index + 1) / total))

        if not texts:
            raise ValueError("文件中没有可索引的有效内容")

        previous_source = _job_repository.source(job["source_id"])
        await engine.vector_store.add_documents(
            texts=texts,
            embeddings=embeddings,
            metadata=metadata,
        )
        new_ingestion_added = True
        _job_repository.update(job_id, progress=90, documents_indexed=len(texts))

        if previous_source and previous_source.get("ingestion_id") != job["ingestion_id"]:
            await engine.vector_store.delete_by_metadata(
                "ingestion_id",
                previous_source["ingestion_id"],
            )

        completed = _job_repository.update(
            job_id,
            status="completed",
            progress=100,
            documents_indexed=len(texts),
            error=None,
        )
        _job_repository.activate_source(completed)
        terminal_status = "completed"
    except Exception as exc:
        logger.exception(f"Knowledge ingestion job {job_id} failed: {exc}")
        if new_ingestion_added:
            try:
                engine = _get_ai_engine()
                await engine.vector_store.delete_by_metadata("ingestion_id", job["ingestion_id"])
            except Exception as rollback_error:
                logger.error(f"Failed to roll back ingestion {job['ingestion_id']}: {rollback_error}")
        _job_repository.update(job_id, status="failed", error=str(exc), progress=0)
        terminal_status = "failed"
    finally:
        knowledge_jobs_in_progress.dec()
        knowledge_jobs_total.labels(status=terminal_status).inc()
        knowledge_job_duration_seconds.labels(status=terminal_status).observe(
            time.perf_counter() - started
        )


async def _process_job(job_id: str) -> None:
    # Serializing the swap step prevents two same-source or same-hash jobs from
    # both becoming active when they are submitted at nearly the same time.
    async with _ingestion_lock:
        await _process_job_locked(job_id)


@router.post("/import", status_code=status.HTTP_202_ACCEPTED)
async def import_knowledge(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    filename = _safe_filename(file.filename)
    engine = _get_ai_engine()
    knowledge_dir = Path(engine.knowledge_loader.knowledge_dir).resolve()
    # Keep job source files outside the loader's recursive scan root. Otherwise
    # a legacy full reload would index every archived version again.
    upload_dir = (knowledge_dir.parent / "knowledge_uploads").resolve()
    upload_dir.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    total_bytes = 0
    temporary = upload_dir / f".{uuid4().hex}.uploading"
    try:
        with temporary.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > settings.knowledge_upload_max_bytes:
                    raise HTTPException(status_code=413, detail="上传文件超过大小限制")
                digest.update(chunk)
                output.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="上传文件为空")
        file_hash = digest.hexdigest()
        stored_path = upload_dir / f"{_source_id(filename)[:12]}_{file_hash[:12]}_{uuid4().hex[:8]}{Path(filename).suffix.lower()}"
        temporary.replace(stored_path)
    finally:
        temporary.unlink(missing_ok=True)

    job = _job_repository.create(
        filename=filename,
        stored_path=stored_path,
        file_hash=file_hash,
        source_id=_source_id(filename),
    )
    background_tasks.add_task(_process_job, job["id"])
    return {"job": _job_repository.public_job(job)}


@router.get("/jobs")
async def list_jobs(limit: int = Query(50, ge=1, le=200)):
    jobs = _job_repository.list(limit=limit)
    return {"items": jobs, "total": len(jobs)}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = _job_repository.get(job_id, public=True)
    if job is None:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return job


@router.post("/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
async def retry_job(job_id: str, background_tasks: BackgroundTasks):
    job = _job_repository.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    if job.get("status") != "failed":
        raise HTTPException(status_code=409, detail="只有失败任务可以重试")
    _job_repository.update(job_id, status="pending", progress=0, error=None)
    background_tasks.add_task(_process_job, job_id)
    return {"job": _job_repository.get(job_id, public=True)}


@router.get("/sources")
async def list_sources():
    sources = _job_repository.list_sources()
    return {"items": sources, "total": len(sources)}


@router.delete("/sources/{source_id}")
async def delete_source(source_id: str):
    source = _job_repository.source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="知识来源不存在")
    engine = _get_ai_engine()
    await engine.vector_store.delete_by_metadata("ingestion_id", source["ingestion_id"])
    _job_repository.remove_source(source_id)
    return {"status": "success", "source_id": source_id}


@router.get("/list")
async def list_knowledge(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    keyword: Optional[str] = None,
):
    try:
        engine = _get_ai_engine()
        items = [
            item
            for item in (_point_item(point) for point in _scroll_points(engine))
            if _matches(item, category, keyword)
        ]
        start = (page - 1) * size
        page_items = items[start:start + size]
        return {
            "items": page_items,
            "total": len(items),
            "page": page,
            "size": size,
            "pages": (len(items) + size - 1) // size,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to list knowledge: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/stats")
async def get_stats():
    try:
        engine = _get_ai_engine()
        items = [_point_item(point) for point in _scroll_points(engine)]
        enabled = sum(1 for item in items if item.get("enabled", True))
        categories: dict[str, int] = {}
        for item in items:
            category = item.get("category")
            if category:
                categories[category] = categories.get(category, 0) + 1
        return {
            "total": len(items),
            "enabled": enabled,
            "disabled": len(items) - enabled,
            "categories": categories,
            **_job_repository.stats(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to get knowledge stats: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.put("/{knowledge_id}")
async def update_knowledge(knowledge_id: str, item: KnowledgeItem):
    try:
        engine = _get_ai_engine()
        vector_store = engine.vector_store
        records = vector_store.client.retrieve(
            collection_name=_collection_name(engine),
            ids=[knowledge_id],
            with_payload=True,
            with_vectors=False,
        )
        if not records:
            raise HTTPException(status_code=404, detail="Knowledge item not found")

        current = records[0]
        current_payload = current.payload or {}
        current_metadata = current_payload.get("metadata") or {}
        text = _knowledge_text(item)
        embedding = await engine.embedding.embed(text)
        vector_store.client.upsert(
            collection_name=_collection_name(engine),
            points=[
                PointStruct(
                    id=current.id,
                    vector=embedding,
                    payload={
                        "text": text,
                        "metadata": _metadata_for_item(
                            item,
                            existing=current_metadata,
                        ),
                    },
                )
            ],
        )
        return {"status": "success", "id": knowledge_id, "item": _model_dump(item)}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to update knowledge {knowledge_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/{knowledge_id}")
async def delete_knowledge(knowledge_id: str):
    try:
        engine = _get_ai_engine()
        vector_store = engine.vector_store
        records = vector_store.client.retrieve(
            collection_name=_collection_name(engine),
            ids=[knowledge_id],
            with_payload=False,
            with_vectors=False,
        )
        if not records:
            raise HTTPException(status_code=404, detail="Knowledge item not found")
        vector_store.client.delete(
            collection_name=_collection_name(engine),
            points_selector=[records[0].id],
        )
        return {"status": "success", "id": knowledge_id}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"Failed to delete knowledge {knowledge_id}: {exc}")
        raise HTTPException(status_code=500, detail=str(exc))
