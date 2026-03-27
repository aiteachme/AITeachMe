"""Storage helpers for knowledge docs build artifacts."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from app.services.upload_support import (
    build_docgen_intermediate_latest_dir,
    build_knowledge_build_lock_path,
    build_knowledge_markdown_build_dir,
    build_knowledge_markdown_dir,
    build_knowledge_manifest_path,
)

STALE_BUILD_LOCK_TTL = timedelta(minutes=30)


class KnowledgeDocsManifest(BaseModel):
    """Metadata describing the published merged knowledge docs."""

    updated_at: datetime
    source_file_ids: list[int] = Field(default_factory=list)
    prompt: str | None = None
    chapter_count: int = 0
    chapter_titles: list[str] = Field(default_factory=list)


class KnowledgeBuildLock(BaseModel):
    """Lock file payload for an in-progress knowledge docs build."""

    requested_at: datetime
    source_file_ids: list[int] = Field(default_factory=list)
    prompt: str | None = None


def _read_build_lock_path(path: Path) -> KnowledgeBuildLock | None:
    if not path.exists():
        return None
    try:
        return KnowledgeBuildLock.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_knowledge_build_lock(subject: str) -> KnowledgeBuildLock | None:
    """Read the subject-level build lock, if present."""

    return _read_build_lock_path(build_knowledge_build_lock_path(subject))


def acquire_knowledge_build_lock(subject: str, lock: KnowledgeBuildLock) -> bool:
    """Create a subject-level build lock atomically."""

    path = build_knowledge_build_lock_path(subject)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = _read_build_lock_path(path)
    if existing is not None and datetime.now(existing.requested_at.tzinfo) - existing.requested_at > STALE_BUILD_LOCK_TTL:
        path.unlink(missing_ok=True)

    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(lock.model_dump_json(indent=2))
    except FileExistsError:
        return False
    return True


def release_knowledge_build_lock(subject: str) -> None:
    """Remove the subject-level build lock if it exists."""

    path = build_knowledge_build_lock_path(subject)
    if path.exists():
        path.unlink()


def is_knowledge_build_locked(subject: str) -> bool:
    """Check whether the subject-level build lock exists."""

    return build_knowledge_build_lock_path(subject).exists()


def read_knowledge_manifest(subject: str) -> KnowledgeDocsManifest | None:
    """Read the published manifest if it exists."""

    path = build_knowledge_manifest_path(subject)
    if not path.exists():
        return None
    return KnowledgeDocsManifest.model_validate_json(path.read_text(encoding="utf-8"))


def write_knowledge_manifest(subject: str, manifest: KnowledgeDocsManifest) -> Path:
    """Persist the published manifest."""

    path = build_knowledge_manifest_path(subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


def clear_docgen_staging(subject: str) -> None:
    """Remove the current knowledge-markdown build directory."""

    for directory in {
        build_knowledge_markdown_build_dir(subject),
        build_docgen_intermediate_latest_dir(subject),
    }:
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)


def clear_published_knowledge_docs_files(subject: str) -> None:
    """Remove published chapter markdown files before replacing them."""

    docs_dir = build_knowledge_markdown_dir(subject)
    for path in docs_dir.glob("chapter_*.md"):
        path.unlink(missing_ok=True)
    merged_path = docs_dir / "merged_knowledge_base.md"
    if merged_path.exists():
        merged_path.unlink()
