"""Storage helpers for knowledge docs build artifacts.

构建锁使用双策略：本地模式用文件锁，云端模式用 Subject 表行锁。
其他所有 I/O（status、manifest、chapter 文件）统一走 ContentStore。
"""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from app.shared.infra.config import get_settings
from app.shared.infra.storage import get_content_store, run_store_sync
from app.utils.path_helpers import (
    build_docgen_intermediate_latest_dir,
    build_knowledge_build_lock_path,
    build_knowledge_markdown_build_dir,
    build_knowledge_markdown_dir,
)
from app.utils.time import utcnow

STALE_BUILD_LOCK_TTL = timedelta(minutes=30)
_STAGE_PROGRESS = {
    "idle": 0,
    "build_accepted": 8,
    "prepare_shared": 24,
    "doc_lane_staged": 62,
    "graph_ready": 74,
    "curriculum_deriving": 86,
    "publishing": 94,
    "completed": 100,
}
_STAGE_DESCRIPTION = {
    "idle": "等待新的知识构建任务",
    "build_accepted": "已接收知识构建请求，正在排队准备材料",
    "prepare_shared": "正在整理文件、切分章节并判定速成课/系统课模式",
    "doc_lane_staged": "知识文档草稿已经就绪，等待图谱与课程结构对齐",
    "graph_ready": "知识图谱主骨架已完成，正在汇总教学结构",
    "curriculum_deriving": "正在生成教学单元、主题树、先修路径与学习计划",
    "publishing": "正在发布正式版知识文档与图谱快照",
    "completed": "最新一轮知识构建已经完成",
    "failed": "本轮知识构建失败，请稍后重试",
    "cancelled": "本轮知识构建已取消",
}


def _build_sample_cards(
    *,
    sample_nodes: list[dict[str, str]],
    digest_mode: str | None,
) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    if digest_mode:
        mode_title = "速成课模式" if digest_mode == "sprint" else "系统课模式"
        mode_summary = (
            "优先压缩为题型、方法与易错点清单。"
            if digest_mode == "sprint"
            else "优先保留概念链路、定义严谨性与先修关系。"
        )
        cards.append(
            {
                "title": mode_title,
                "card_type": "mode",
                "summary": mode_summary,
            }
        )

    for sample in sample_nodes[:3]:
        name = str(sample.get("name", "")).strip()
        node_type = str(sample.get("type", "Topic")).strip() or "Topic"
        if not name:
            continue
        summary = {
            "Topic": "正在围绕这个主题聚合知识主干与相邻章节。",
            "Concept": "正在补齐定义、辨析点与核心联系。",
            "Method": "正在提炼步骤、适用场景与典型题型。",
        }.get(node_type, "正在把这个节点整理进知识结构。")
        cards.append(
            {
                "title": name,
                "card_type": node_type.lower(),
                "summary": summary,
            }
        )
    return cards[:4]


def _hydrate_runtime_status(status: "KnowledgeBuildRuntimeStatus") -> "KnowledgeBuildRuntimeStatus":
    if not status.current_stage_description:
        status.current_stage_description = _STAGE_DESCRIPTION.get(status.stage, "正在构建知识内容")

    stage_progress = _STAGE_PROGRESS.get(status.stage)
    if status.status == "completed":
        status.progress_pct = 100
    elif stage_progress is not None:
        status.progress_pct = max(int(status.progress_pct), int(stage_progress))
    status.progress_pct = max(0, min(int(status.progress_pct), 100))

    if status.current_chunk is None and status.processed_chunks > 0:
        status.current_chunk = status.processed_chunks
    if status.status == "completed" and status.total_chunks > 0:
        status.current_chunk = status.total_chunks
        status.processed_chunks = status.total_chunks

    if status.status == "completed":
        status.estimated_remaining_seconds = 0
    elif status.status in {"failed", "cancelled", "idle"}:
        status.estimated_remaining_seconds = None
    elif 0 < status.progress_pct < 100:
        elapsed_seconds = max(1, int((utcnow() - status.requested_at).total_seconds()))
        remaining = int(elapsed_seconds * (100 - status.progress_pct) / max(status.progress_pct, 1))
        status.estimated_remaining_seconds = max(3, remaining)
    else:
        status.estimated_remaining_seconds = None

    if not status.sample_cards:
        status.sample_cards = _build_sample_cards(
            sample_nodes=status.sample_nodes,
            digest_mode=status.digest_mode,
        )
    return status


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
    build_session_id: str | None = None
    source_file_ids: list[int] = Field(default_factory=list)
    prompt: str | None = None
    error_message: str | None = None
    draft_available: bool = False
    draft_updated_at: datetime | None = None
    staged_chapter_count: int = 0
    published_doc_count: int = 0
    # Progress tracking for SSE
    progress_pct: int = 0
    discovered_node_count: int = 0
    discovered_node_types: dict[str, int] = Field(default_factory=dict)
    digest_mode: str | None = None
    sample_nodes: list[dict[str, str]] = Field(default_factory=list)
    estimated_remaining_seconds: int | None = None
    current_stage_description: str | None = None
    current_chunk: int | None = None
    processed_chunks: int = 0
    total_chunks: int = 0
    sample_cards: list[dict[str, str]] = Field(default_factory=list)
    mode_reason: str | None = None


# ── Build Lock ──
# 注意：构建锁需要原子性保证，云端走 DB 行锁、本地走文件锁，
# 这里 is_cloud_mode 判断有合理理由保留（两种完全不同的锁机制）。

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


# ── Build Status（统一走 ContentStore） ──

def read_knowledge_build_status(subject: str) -> KnowledgeBuildRuntimeStatus | None:
    """Read the runtime build-status payload if it exists."""

    cs = get_content_store()
    key = cs.build_status_key(subject)
    status = run_store_sync(cs.read_json, key, KnowledgeBuildRuntimeStatus)
    return _hydrate_runtime_status(status) if status is not None else None


def write_knowledge_build_status(
    subject: str,
    status: KnowledgeBuildRuntimeStatus,
) -> str:
    """Persist the runtime build-status payload."""

    cs = get_content_store()
    key = cs.build_status_key(subject)
    run_store_sync(cs.write_json, key, status)
    return key


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
    updated = _hydrate_runtime_status(updated)
    write_knowledge_build_status(subject, updated)
    return updated


def clear_knowledge_build_status(subject: str) -> None:
    """Remove runtime build-status metadata."""

    cs = get_content_store()
    run_store_sync(cs.delete, cs.build_status_key(subject), default=None)


# ── Manifest（统一走 ContentStore） ──

def read_knowledge_manifest(subject: str) -> KnowledgeDocsManifest | None:
    """Read the published manifest if it exists."""

    cs = get_content_store()
    return run_store_sync(cs.read_json, cs.build_manifest_key(subject), KnowledgeDocsManifest)


def write_knowledge_manifest(subject: str, manifest: KnowledgeDocsManifest) -> str:
    """Persist the published manifest."""

    cs = get_content_store()
    key = cs.build_manifest_key(subject)
    run_store_sync(cs.write_json, key, manifest)
    return key


# ── Cleanup（统一走 ContentStore） ──

def clear_docgen_staging(subject: str) -> None:
    """Remove the current knowledge-markdown build directory."""

    cs = get_content_store()
    run_store_sync(cs.delete_prefix, cs.knowledge_build_prefix(subject), default=0)

    # local 模式还需要清理 intermediate 目录（docgen 本地中间产物）
    settings = get_settings()
    if settings.is_local_mode:
        intermediate_dir = build_docgen_intermediate_latest_dir(subject)
        if intermediate_dir.exists():
            shutil.rmtree(intermediate_dir, ignore_errors=True)


def clear_published_knowledge_docs_files(subject: str) -> None:
    """Remove published chapter markdown files before replacing them."""

    cs = get_content_store()
    keys = run_store_sync(cs.list_prefix, f"{subject}/knowledge_markdowns/", default=[])
    for key in keys:
        filename = key.rsplit("/", 1)[-1] if "/" in key else key
        if filename.startswith("chapter_") or filename == "merged_knowledge_base.md":
            run_store_sync(cs.delete, key, default=None)


def clear_knowledge_runtime_artifacts(subject: str) -> None:
    """Remove published and staging knowledge-doc artifacts for one subject."""

    clear_docgen_staging(subject)
    clear_knowledge_build_status(subject)
    clear_published_knowledge_docs_files(subject)

    cs = get_content_store()
    run_store_sync(cs.delete, cs.build_manifest_key(subject), default=None)

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
