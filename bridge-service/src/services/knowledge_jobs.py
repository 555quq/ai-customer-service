"""Persistent repository for asynchronous knowledge ingestion jobs."""

from __future__ import annotations

import json
import os
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4


TERMINAL_STATUSES = {"completed", "failed"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class KnowledgeJobRepository:
    """Store ingestion jobs and active source manifests in one atomic JSON file."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def _empty(self) -> dict[str, Any]:
        return {"version": 1, "jobs": {}, "sources": {}}

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return self._empty()
        if not isinstance(data, dict):
            return self._empty()
        data.setdefault("version", 1)
        data.setdefault("jobs", {})
        data.setdefault("sources", {})
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    @staticmethod
    def public_job(job: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(job)
        result.pop("stored_path", None)
        return result

    def create(
        self,
        *,
        filename: str,
        stored_path: Path,
        file_hash: str,
        source_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            created_at = _now()
            job = {
                "id": uuid4().hex,
                "filename": filename,
                "stored_path": str(stored_path),
                "file_hash": file_hash,
                "source_id": source_id,
                "ingestion_id": uuid4().hex,
                "status": "pending",
                "progress": 0,
                "documents_total": 0,
                "documents_indexed": 0,
                "error": None,
                "duplicate_of": None,
                "attempts": 0,
                "created_at": created_at,
                "updated_at": created_at,
            }
            data["jobs"][job["id"]] = job
            self._write(data)
            return deepcopy(job)

    def get(self, job_id: str, *, public: bool = False) -> Optional[dict[str, Any]]:
        with self._lock:
            job = self._read()["jobs"].get(job_id)
            if job is None:
                return None
            return self.public_job(job) if public else deepcopy(job)

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._read()["jobs"].values())
            jobs.sort(key=lambda job: job.get("created_at", ""), reverse=True)
            return [self.public_job(job) for job in jobs[:limit]]

    def update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            job = data["jobs"].get(job_id)
            if job is None:
                raise KeyError(job_id)
            job.update(changes)
            job["updated_at"] = _now()
            self._write(data)
            return deepcopy(job)

    def find_completed_hash(self, file_hash: str, *, exclude_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            for job in self._read()["jobs"].values():
                if (
                    job.get("id") != exclude_id
                    and job.get("file_hash") == file_hash
                    and job.get("status") == "completed"
                ):
                    return deepcopy(job)
        return None

    def source(self, source_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            value = self._read()["sources"].get(source_id)
            return deepcopy(value) if value else None

    def activate_source(self, job: dict[str, Any]) -> None:
        with self._lock:
            data = self._read()
            data["sources"][job["source_id"]] = {
                "source_id": job["source_id"],
                "filename": job["filename"],
                "file_hash": job["file_hash"],
                "ingestion_id": job["ingestion_id"],
                "job_id": job["id"],
                "documents": job.get("documents_indexed", 0),
                "updated_at": _now(),
            }
            self._write(data)

    def list_sources(self) -> list[dict[str, Any]]:
        with self._lock:
            sources = list(self._read()["sources"].values())
            sources.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
            return deepcopy(sources)

    def remove_source(self, source_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            data = self._read()
            source = data["sources"].pop(source_id, None)
            if source is not None:
                self._write(data)
            return deepcopy(source) if source else None

    def stats(self) -> dict[str, int]:
        with self._lock:
            data = self._read()
            jobs = list(data["jobs"].values())
            return {
                "sources": len(data["sources"]),
                "jobs": len(jobs),
                "pending_jobs": sum(job.get("status") == "pending" for job in jobs),
                "processing_jobs": sum(job.get("status") == "processing" for job in jobs),
                "failed_jobs": sum(job.get("status") == "failed" for job in jobs),
            }
