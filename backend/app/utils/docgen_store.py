"""Storage helpers for knowledge docs build artifacts.

本地模式使用文件系统，云端模式通过 ArtifactStore 抽象操作对象存储。
构建锁在云端模式下使用 Subject 表的 build_lock_* 字段（DB 行锁），
避免依赖特定文件系统实现。
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from app.shared.infra.config import get_settings
from app.shared.infra.storage import get_artifact_store, run_store_sync
from app.utils.path_helpers import (
    build_docgen_intermediate_latest_dir,
    build_knowledge_build_lock_path,
    build_knowledge_build_status_path,
    build_knowledge_markdown_build_dir,
    build_knowledge_markdown_dir,
    build_knowledge_manifest_path,
)
from app.utils.time import utcnow

STALE_BUILD_LOCK_TTL = timedelta(minutes=30)


# ── 云端 storage_key 构建 ──

def _cloud_key(subject: str, filename: str) -> str:
    """构建 cloud 模式下的 storage_key，路径结构与本地一致。"""
    return f"{subject}/knowledge_markdowns/{filename}"


# ── Pydantic models ──

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


class KnowledgeBuildRuntimeStatus(BaseModel):
    """Runtime metadata for the current or most recent knowledge build."""

    requested_at: datetime
    status: str = "accepted"
    stage: str = "build_accepted"
    source_file_ids: list[int] = Field(default_factory=list)
    prompt: str | None = None
    error_message: str | None = None
    draft_available: bool = False
    draft_updated_at: datetime | None = None
    staged_chapter_count: int = 0
    published_doc_count: int = 0


# ── Build Lock ──

def _read_build_lock_path(path: Path) -> KnowledgeBuildLock | None:
    if not path.exists():
        return None
    try:
        return KnowledgeBuildLock.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_knowledge_build_lock(subject: str) -> KnowledgeBuildLock | None:
    """Read the subject-level build lock, if present."""

    settings = get_settings()
    if settings.is_cloud_mode:
        return _cloud_read_build_lock(subject)
    return _read_build_lock_path(build_knowledge_build_lock_path(subject))


def acquire_knowledge_build_lock(subject: str, lock: KnowledgeBuildLock) -> bool:
    """Create a subject-level build lock atomically."""

    settings = get_settings()
    if settings.is_cloud_mode:
        return _cloud_acquire_build_lock(subject, lock)

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

    settings = get_settings()
    if settings.is_cloud_mode:
        _cloud_release_build_lock(subject)
        return

    path = build_knowledge_build_lock_path(subject)
    if path.exists():
        path.unlink()


def is_knowledge_build_locked(subject: str) -> bool:
    """Check whether the subject-level build lock exists."""

    settings = get_settings()
    if settings.is_cloud_mode:
        return _cloud_read_build_lock(subject) is not None
    return build_knowledge_build_lock_path(subject).exists()


# ── Build Lock: 云端实现（DB 行锁） ──

def _cloud_read_build_lock(subject: str) -> KnowledgeBuildLock | None:
    """云端模式：从 Subject 表读取构建锁。"""
    from sqlmodel import select
    from app.shared.infra.database import managed_session
    from app.models.subject import Subject

    with managed_session() as session:
        record = session.exec(select(Subject).where(Subject.slug == subject)).first()
        if record is None or record.build_lock_holder is None:
            return None
        # 检查过期
        if record.build_lock_at is not None:
            now = datetime.now(record.build_lock_at.tzinfo) if record.build_lock_at.tzinfo else datetime.utcnow()
            if now - record.build_lock_at > STALE_BUILD_LOCK_TTL:
                record.build_lock_holder = None
                record.build_lock_at = None
                session.add(record)
                session.commit()
                return None
        try:
            return KnowledgeBuildLock.model_validate_json(record.build_lock_holder)
        except Exception:
            return None


def _cloud_acquire_build_lock(subject: str, lock: KnowledgeBuildLock) -> bool:
    """云端模式：通过 Subject 表原子设置构建锁。"""
    from sqlmodel import select
    from app.shared.infra.database import managed_session
    from app.models.subject import Subject

    with managed_session() as session:
        record = session.exec(select(Subject).where(Subject.slug == subject)).first()
        if record is None:
            return False

        # 已有有效锁 → 获取失败
        if record.build_lock_holder is not None:
            if record.build_lock_at is not None:
                now = datetime.now(record.build_lock_at.tzinfo) if record.build_lock_at.tzinfo else datetime.utcnow()
                if now - record.build_lock_at <= STALE_BUILD_LOCK_TTL:
                    return False
            # 否则视为过期，可以覆盖

        record.build_lock_holder = lock.model_dump_json()
        record.build_lock_at = utcnow()
        session.add(record)
        session.commit()
    return True


def _cloud_release_build_lock(subject: str) -> None:
    """云端模式：清除 Subject 表中的构建锁。"""
    from sqlmodel import select
    from app.shared.infra.database import managed_session
    from app.models.subject import Subject

    with managed_session() as session:
        record = session.exec(select(Subject).where(Subject.slug == subject)).first()
        if record is not None and record.build_lock_holder is not None:
            record.build_lock_holder = None
            record.build_lock_at = None
            session.add(record)
            session.commit()


# ── Build Status ──

def read_knowledge_build_status(subject: str) -> KnowledgeBuildRuntimeStatus | None:
    """Read the runtime build-status payload if it exists."""

    settings = get_settings()
    if settings.is_cloud_mode:
        key = _cloud_key(subject, "build_status.json")
        store = get_artifact_store()
        data: bytes | None = run_store_sync(store.read_bytes, key, default=None)
        if data is None:
            return None
        try:
            return KnowledgeBuildRuntimeStatus.model_validate_json(data.decode("utf-8"))
        except Exception:
            return None

    path = build_knowledge_build_status_path(subject)
    if not path.exists():
        return None
    try:
        return KnowledgeBuildRuntimeStatus.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_knowledge_build_status(
    subject: str,
    status: KnowledgeBuildRuntimeStatus,
) -> Path | str:
    """Persist the runtime build-status payload."""

    settings = get_settings()
    if settings.is_cloud_mode:
        key = _cloud_key(subject, "build_status.json")
        store = get_artifact_store()
        run_store_sync(store.write_bytes, key, status.model_dump_json(indent=2).encode("utf-8"))
        return key

    path = build_knowledge_build_status_path(subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(status.model_dump_json(indent=2), encoding="utf-8")
    return path


def update_knowledge_build_status(
    subject: str,
    **kwargs: object,
) -> KnowledgeBuildRuntimeStatus:
    """Merge updates into the runtime build-status payload."""

    existing = read_knowledge_build_status(subject)
    requested_at = kwargs.get("requested_at")
    if existing is None:
        existing = KnowledgeBuildRuntimeStatus(
            requested_at=requested_at if isinstance(requested_at, datetime) else utcnow(),
        )
    updated = existing.model_copy(update=kwargs)
    write_knowledge_build_status(subject, updated)
    return updated


def clear_knowledge_build_status(subject: str) -> None:
    """Remove runtime build-status metadata."""

    settings = get_settings()
    if settings.is_cloud_mode:
        key = _cloud_key(subject, "build_status.json")
        store = get_artifact_store()
        run_store_sync(store.delete, key, default=None)
        return

    path = build_knowledge_build_status_path(subject)
    if path.exists():
        path.unlink()


# ── Manifest ──

def read_knowledge_manifest(subject: str) -> KnowledgeDocsManifest | None:
    """Read the published manifest if it exists."""

    settings = get_settings()
    if settings.is_cloud_mode:
        key = _cloud_key(subject, "manifest.json")
        store = get_artifact_store()
        data: bytes | None = run_store_sync(store.read_bytes, key, default=None)
        if data is None:
            return None
        try:
            return KnowledgeDocsManifest.model_validate_json(data.decode("utf-8"))
        except Exception:
            return None

    path = build_knowledge_manifest_path(subject)
    if not path.exists():
        return None
    return KnowledgeDocsManifest.model_validate_json(path.read_text(encoding="utf-8"))


def write_knowledge_manifest(subject: str, manifest: KnowledgeDocsManifest) -> Path | str:
    """Persist the published manifest."""

    settings = get_settings()
    if settings.is_cloud_mode:
        key = _cloud_key(subject, "manifest.json")
        store = get_artifact_store()
        run_store_sync(store.write_bytes, key, manifest.model_dump_json(indent=2).encode("utf-8"))
        return key

    path = build_knowledge_manifest_path(subject)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    return path


# ── Cleanup ──

def clear_docgen_staging(subject: str) -> None:
    """Remove the current knowledge-markdown build directory."""

    settings = get_settings()
    if settings.is_cloud_mode:
        store = get_artifact_store()
        run_store_sync(store.delete_prefix, f"{subject}/knowledge_markdowns/_build/", default=0)
        return

    for directory in {
        build_knowledge_markdown_build_dir(subject),
        build_docgen_intermediate_latest_dir(subject),
    }:
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)


def clear_published_knowledge_docs_files(subject: str) -> None:
    """Remove published chapter markdown files before replacing them."""

    settings = get_settings()
    if settings.is_cloud_mode:
        store = get_artifact_store()
        # 删除 chapter_*.md 和 merged_knowledge_base.md
        keys = run_store_sync(
            store.list_prefix,
            f"{subject}/knowledge_markdowns/",
            default=[],
        )
        for key in keys:
            filename = key.rsplit("/", 1)[-1] if "/" in key else key
            if filename.startswith("chapter_") or filename == "merged_knowledge_base.md":
                run_store_sync(store.delete, key, default=None)
        return

    docs_dir = build_knowledge_markdown_dir(subject)
    for path in docs_dir.glob("chapter_*.md"):
        path.unlink(missing_ok=True)
    merged_path = docs_dir / "merged_knowledge_base.md"
    if merged_path.exists():
        merged_path.unlink()


def clear_knowledge_runtime_artifacts(subject: str) -> None:
    """Remove published and staging knowledge-doc artifacts for one subject."""

    clear_docgen_staging(subject)
    clear_knowledge_build_status(subject)
    clear_published_knowledge_docs_files(subject)

    settings = get_settings()
    if settings.is_cloud_mode:
        store = get_artifact_store()
        run_store_sync(store.delete, _cloud_key(subject, "manifest.json"), default=None)
    else:
        build_knowledge_manifest_path(subject).unlink(missing_ok=True)

    release_knowledge_build_lock(subject)


__all__ = [
    "KnowledgeBuildLock",
    "KnowledgeBuildRuntimeStatus",
    "KnowledgeDocsManifest",
    "STALE_BUILD_LOCK_TTL",
    "acquire_knowledge_build_lock",
    "clear_docgen_staging",
    "clear_knowledge_build_status",
    "clear_knowledge_runtime_artifacts",
    "clear_published_knowledge_docs_files",
    "is_knowledge_build_locked",
    "read_knowledge_build_lock",
    "read_knowledge_build_status",
    "read_knowledge_manifest",
    "release_knowledge_build_lock",
    "update_knowledge_build_status",
    "write_knowledge_build_status",
    "write_knowledge_manifest",
]
