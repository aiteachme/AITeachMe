"""Storage helpers for knowledge docs build artifacts."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

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


def read_knowledge_build_status(subject: str) -> KnowledgeBuildRuntimeStatus | None:
    """Read the runtime build-status payload if it exists."""

    path = build_knowledge_build_status_path(subject)
    if not path.exists():
        return None
    try:
        return _hydrate_runtime_status(
            KnowledgeBuildRuntimeStatus.model_validate_json(path.read_text(encoding="utf-8"))
        )
    except Exception:
        return None


def write_knowledge_build_status(
    subject: str,
    status: KnowledgeBuildRuntimeStatus,
) -> Path:
    """Persist the runtime build-status payload."""

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
    updated = _hydrate_runtime_status(updated)
    write_knowledge_build_status(subject, updated)
    return updated


def clear_knowledge_build_status(subject: str) -> None:
    """Remove runtime build-status metadata."""

    path = build_knowledge_build_status_path(subject)
    if path.exists():
        path.unlink()


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


def clear_knowledge_runtime_artifacts(subject: str) -> None:
    """Remove published and staging knowledge-doc artifacts for one subject."""

    clear_docgen_staging(subject)
    clear_knowledge_build_status(subject)
    clear_published_knowledge_docs_files(subject)
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
