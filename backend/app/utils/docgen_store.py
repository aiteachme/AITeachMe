"""Storage helpers for knowledge-doc build artifacts."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock, RLock

from pydantic import BaseModel, Field

from app.shared.infra.runtime import is_cloud_mode, is_local_mode
from app.shared.infra.storage import get_content_store, run_store_sync
from app.utils.path_helpers import (
    build_docgen_intermediate_latest_dir,
    build_knowledge_build_lock_path,
)
from app.utils.time import ensure_utc_datetime, utcnow

STALE_BUILD_LOCK_TTL = timedelta(minutes=30)

_STAGE_PROGRESS = {
    "idle": 0,
    "build_accepted": 8,
    "prepare_shared": 18,
    "planner_confirmed": 22,
    "preparing_docgen_context": 30,
    "dispatch_ready": 34,
    "building_document_backbone": 38,
    "generating_chapters": 48,
    "enhancing_chapters": 64,
    "chapters_enhanced": 72,
    "reviewing_content": 76,
    "content_reviewed": 80,
    "repairing_or_routing": 82,
    "repair_routed": 84,
    "merge_reviewed": 86,
    "titles_finalized": 88,
    "injecting_examine": 84,
    "doc_lane_staged": 90,
    "graph_ready": 92,
    "publishing": 97,
    "completed": 100,
    "failed": 0,
    "cancelled": 0,
}

_STAGE_DESCRIPTION = {
    "idle": "当前没有正在进行的知识文档构建任务。",
    "build_accepted": "已接收构建请求，等待启动。",
    "prepare_shared": "正在准备共享资料上下文。",
    "planner_confirmed": "构建方案已确认，准备按章节启动。",
    "preparing_docgen_context": "正在增强大纲、识别写作意图并摘要材料。",
    "dispatch_ready": "章节执行计划 seed 已生成，准备构建知识骨架。",
    "building_document_backbone": "正在统一术语、主张、证据和易混点。",
    "generating_chapters": "正在按章节检索、整理证据并生成草稿。",
    "enhancing_chapters": "正在增强 Markdown、公式与媒体占位内容。",
    "chapters_enhanced": "章节增强已完成。",
    "reviewing_content": "正在复核章节覆盖、证据和整本一致性。",
    "content_reviewed": "内容复核已完成。",
    "repairing_or_routing": "正在记录复核回流动作。",
    "repair_routed": "复核回流动作已记录。",
    "merge_reviewed": "整本文档检查完成，准备标题收口。",
    "titles_finalized": "章节标题已收口，准备发布。",
    "injecting_examine": "正在注入练习与自检内容。",
    "doc_lane_staged": "文档草稿已暂存，等待统一发布。",
    "graph_ready": "知识图谱已就绪。",
    "publishing": "正在发布最终知识文档。",
    "completed": "知识文档构建完成。",
    "failed": "知识文档构建失败。",
    "cancelled": "知识文档构建已取消。",
}

_STATUS_LOCK_GUARD = Lock()
_STATUS_LOCKS: dict[str, RLock] = {}


class KnowledgeDocsManifest(BaseModel):
    """Metadata describing the published merged knowledge docs."""

    updated_at: datetime
    version_no: int = 0
    source_file_ids: list[int] = Field(default_factory=list)
    prompt: str | None = None
    chapter_count: int = 0
    chapter_titles: list[str] = Field(default_factory=list)
    docgen_manifest_key: str | None = None
    merge_review_report: dict[str, object] = Field(default_factory=dict)


class KnowledgeBuildLock(BaseModel):
    """Lock file payload for an in-progress knowledge-doc build."""

    requested_at: datetime
    source_file_ids: list[int] = Field(default_factory=list)
    prompt: str | None = None


class KnowledgeBuildRuntimeStatus(BaseModel):
    """Runtime metadata for the current or most recent build."""

    requested_at: datetime
    status: str = "accepted"
    stage: str = "build_accepted"
    build_session_id: str | None = None
    planner_session_id: str | None = None
    confirmed_plan_id: str | None = None
    source_file_ids: list[int] = Field(default_factory=list)
    prompt: str | None = None
    error_message: str | None = None
    draft_available: bool = False
    draft_updated_at: datetime | None = None
    staged_chapter_count: int = 0
    published_doc_count: int = 0
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
    plan_summary: str | None = None
    chapter_progress: list[dict[str, object]] = Field(default_factory=list)
    recent_events: list[dict[str, object]] = Field(default_factory=list)


def _get_status_lock(subject: str) -> RLock:
    with _STATUS_LOCK_GUARD:
        lock = _STATUS_LOCKS.get(subject)
        if lock is None:
            lock = RLock()
            _STATUS_LOCKS[subject] = lock
        return lock


def _build_sample_cards(
    *,
    sample_nodes: list[dict[str, str]],
    digest_mode: str | None,
) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    if digest_mode:
        cards.append(
            {
                "title": "构建模式",
                "card_type": "mode",
                "summary": (
                    "冲刺模式更强调快速抓重点、贴近题型和考前回顾。"
                    if digest_mode == "sprint"
                    else "系统模式更强调概念完整、推导清晰和结构化学习。"
                ),
            }
        )

    for sample in sample_nodes[:3]:
        name = str(sample.get("name", "")).strip()
        knowledge_unit_type = str(sample.get("type", "concept")).strip() or "concept"
        if not name:
            continue
        cards.append(
            {
                "title": name,
                "card_type": knowledge_unit_type.lower(),
                "summary": f"这是当前构建过程中抽取到的 {knowledge_unit_type.lower()} 预览。",
            }
        )
    return cards[:4]


def _normalize_chapter_progress_entry(entry: dict[str, object]) -> dict[str, object]:
    chapter_index = int(entry.get("chapter_index", 0) or 0)
    fallback_title = f"第 {chapter_index} 章" if chapter_index > 0 else "未命名章节"
    title = str(entry.get("title") or fallback_title).strip() or fallback_title
    return {
        "chapter_index": chapter_index,
        "title": title,
        "status": str(entry.get("status") or "planned").strip() or "planned",
        "source_count": int(entry.get("source_count", 0) or 0),
        "local_hits": int(entry.get("local_hits", 0) or 0),
        "web_hits": int(entry.get("web_hits", 0) or 0),
        "query_count": int(entry.get("query_count", 0) or 0),
        "word_count": int(entry.get("word_count", 0) or 0),
        "fallback_used": bool(entry.get("fallback_used", False)),
    }


def _normalize_compact_string_list(value: object, *, limit: int = 5) -> list[str]:
    if not isinstance(value, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
        if len(normalized) >= limit:
            break
    return normalized


def _normalize_recent_event_entry(entry: dict[str, object]) -> dict[str, object]:
    created_at = entry.get("created_at")
    if not isinstance(created_at, datetime):
        created_at = utcnow()
    chapter_index = entry.get("chapter_index")
    normalized_chapter_index = int(chapter_index) if chapter_index not in (None, "") else None
    title = str(entry.get("title") or "").strip() or None
    return {
        "stage": str(entry.get("stage") or "").strip(),
        "chapter_index": normalized_chapter_index,
        "title": title,
        "summary": str(entry.get("summary") or "").strip(),
        "created_at": created_at,
        "domains": _normalize_compact_string_list(entry.get("domains"), limit=4),
        "source_titles": _normalize_compact_string_list(entry.get("source_titles"), limit=4),
        "source_urls": _normalize_compact_string_list(entry.get("source_urls"), limit=4),
    }


def _hydrate_runtime_status(status: KnowledgeBuildRuntimeStatus) -> KnowledgeBuildRuntimeStatus:
    status.requested_at = ensure_utc_datetime(status.requested_at) or utcnow()
    if not status.current_stage_description:
        status.current_stage_description = _STAGE_DESCRIPTION.get(status.stage, "知识文档构建进行中。")

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

    status.chapter_progress = [
        _normalize_chapter_progress_entry(dict(item))
        for item in list(status.chapter_progress or [])
    ]
    status.chapter_progress.sort(key=lambda item: int(item.get("chapter_index", 0) or 0))
    status.recent_events = [
        _normalize_recent_event_entry(dict(item))
        for item in list(status.recent_events or [])
        if str(dict(item).get("summary") or "").strip()
    ]
    status.recent_events.sort(
        key=lambda item: (
            item.get("created_at") if isinstance(item.get("created_at"), datetime) else utcnow()
        ),
        reverse=True,
    )
    if not status.sample_cards:
        status.sample_cards = _build_sample_cards(
            sample_nodes=status.sample_nodes,
            digest_mode=status.digest_mode,
        )
    return status


def _read_build_lock_path(path: Path) -> KnowledgeBuildLock | None:
    if not path.exists():
        return None
    try:
        return KnowledgeBuildLock.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def read_knowledge_build_lock(subject: str) -> KnowledgeBuildLock | None:
    """Read the subject-level build lock, if present."""

    if is_cloud_mode():
        return _cloud_read_build_lock(subject)
    return _read_build_lock_path(build_knowledge_build_lock_path(subject))


def acquire_knowledge_build_lock(subject: str, lock: KnowledgeBuildLock) -> bool:
    """Create a subject-level build lock atomically."""

    if is_cloud_mode():
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

    if is_cloud_mode():
        _cloud_release_build_lock(subject)
        return

    path = build_knowledge_build_lock_path(subject)
    if path.exists():
        path.unlink()


def is_knowledge_build_locked(subject: str) -> bool:
    """Check whether the subject-level build lock exists."""

    if is_cloud_mode():
        return _cloud_read_build_lock(subject) is not None
    return build_knowledge_build_lock_path(subject).exists()


def _cloud_read_build_lock(subject: str) -> KnowledgeBuildLock | None:
    from sqlmodel import select

    from app.models.subject import Subject
    from app.shared.infra.database import managed_session

    with managed_session() as session:
        record = session.exec(select(Subject).where(Subject.slug == subject)).first()
        if record is None or record.build_lock_holder is None:
            return None
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
    from sqlmodel import select

    from app.models.subject import Subject
    from app.shared.infra.database import managed_session

    with managed_session() as session:
        record = session.exec(select(Subject).where(Subject.slug == subject)).first()
        if record is None:
            return False

        if record.build_lock_holder is not None:
            if record.build_lock_at is not None:
                now = datetime.now(record.build_lock_at.tzinfo) if record.build_lock_at.tzinfo else datetime.utcnow()
                if now - record.build_lock_at <= STALE_BUILD_LOCK_TTL:
                    return False

        record.build_lock_holder = lock.model_dump_json()
        record.build_lock_at = utcnow()
        session.add(record)
        session.commit()
    return True


def _cloud_release_build_lock(subject: str) -> None:
    from sqlmodel import select

    from app.models.subject import Subject
    from app.shared.infra.database import managed_session

    with managed_session() as session:
        record = session.exec(select(Subject).where(Subject.slug == subject)).first()
        if record is not None and record.build_lock_holder is not None:
            record.build_lock_holder = None
            record.build_lock_at = None
            session.add(record)
            session.commit()


def read_knowledge_build_status(subject: str) -> KnowledgeBuildRuntimeStatus | None:
    """Read the runtime build-status payload if it exists."""

    cs = get_content_store()
    key = cs.build_status_key(subject)
    status = run_store_sync(cs.read_json, key, KnowledgeBuildRuntimeStatus)
    return _hydrate_runtime_status(status) if status is not None else None


def write_knowledge_build_status(subject: str, status: KnowledgeBuildRuntimeStatus) -> str:
    """Persist the runtime build-status payload."""

    cs = get_content_store()
    key = cs.build_status_key(subject)
    run_store_sync(cs.write_json, key, status)
    return key


def update_knowledge_build_status(subject: str, **kwargs: object) -> KnowledgeBuildRuntimeStatus:
    """Merge updates into the runtime build-status payload."""

    with _get_status_lock(subject):
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


def upsert_knowledge_build_chapter_progress(
    subject: str,
    *,
    chapter_progress: dict[str, object],
    requested_at: datetime | None = None,
) -> KnowledgeBuildRuntimeStatus:
    """Merge one chapter progress entry into the runtime build status."""

    with _get_status_lock(subject):
        existing = read_knowledge_build_status(subject)
        if existing is None:
            existing = KnowledgeBuildRuntimeStatus(requested_at=requested_at or utcnow())
        normalized = _normalize_chapter_progress_entry(chapter_progress)
        current = {
            int(item.get("chapter_index", 0) or 0): _normalize_chapter_progress_entry(dict(item))
            for item in list(existing.chapter_progress or [])
        }
        chapter_index = int(normalized["chapter_index"])
        merged = dict(current.get(chapter_index, {}))
        merged.update(normalized)
        current[chapter_index] = _normalize_chapter_progress_entry(merged)
        existing.chapter_progress = [current[key] for key in sorted(current)]
        existing = _hydrate_runtime_status(existing)
        write_knowledge_build_status(subject, existing)
        return existing


def append_knowledge_build_recent_event(
    subject: str,
    *,
    event: dict[str, object],
    requested_at: datetime | None = None,
    limit: int = 24,
) -> KnowledgeBuildRuntimeStatus:
    """Append one recent event into the runtime build status."""

    with _get_status_lock(subject):
        existing = read_knowledge_build_status(subject)
        if existing is None:
            existing = KnowledgeBuildRuntimeStatus(requested_at=requested_at or utcnow())
        normalized = _normalize_recent_event_entry(event)
        existing.recent_events = [normalized, *list(existing.recent_events or [])][: max(1, int(limit))]
        existing = _hydrate_runtime_status(existing)
        write_knowledge_build_status(subject, existing)
        return existing


def clear_knowledge_build_status(subject: str) -> None:
    """Remove runtime build-status metadata."""

    cs = get_content_store()
    run_store_sync(cs.delete, cs.build_status_key(subject), default=None)


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


def clear_docgen_staging(subject: str) -> None:
    """Remove the current knowledge-markdown build directory."""

    cs = get_content_store()
    run_store_sync(cs.delete_prefix, cs.knowledge_build_prefix(subject), default=0)

    if is_local_mode():
        intermediate_dir = build_docgen_intermediate_latest_dir(subject)
        if intermediate_dir.exists():
            shutil.rmtree(intermediate_dir, ignore_errors=True)


def clear_published_knowledge_docs_files(subject: str) -> None:
    """Remove all published knowledge-doc files, including archived versions."""

    cs = get_content_store()
    keys = run_store_sync(cs.list_prefix, f"{subject}/knowledge_markdowns/", default=[])
    for key in keys:
        relative = key.removeprefix(f"{subject}/knowledge_markdowns/")
        filename = relative.rsplit("/", 1)[-1] if "/" in relative else relative
        if (
            filename.startswith("chapter_")
            or filename == "merged_knowledge_base.md"
            or filename == "docgen_manifest.json"
            or relative.startswith("versions/")
        ):
            run_store_sync(cs.delete, key, default=None)


def clear_current_published_knowledge_docs_files(subject: str) -> None:
    """Remove only the current published chapter markdown files."""

    cs = get_content_store()
    keys = run_store_sync(cs.list_prefix, f"{subject}/knowledge_markdowns/", default=[])
    for key in keys:
        relative = key.removeprefix(f"{subject}/knowledge_markdowns/")
        if relative.startswith("versions/"):
            continue
        filename = relative.rsplit("/", 1)[-1] if "/" in relative else relative
        if filename.startswith("chapter_") or filename in {"merged_knowledge_base.md", "docgen_manifest.json"}:
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
    "append_knowledge_build_recent_event",
    "clear_current_published_knowledge_docs_files",
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
    "upsert_knowledge_build_chapter_progress",
    "write_knowledge_build_status",
    "write_knowledge_manifest",
]
