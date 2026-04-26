"""Storage helpers for subject knowledge build runtime and artifacts."""

from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock, RLock
from typing import Literal

from pydantic import BaseModel, Field

from app.shared.infra.runtime import is_cloud_mode, is_local_mode
from app.shared.infra.storage import (
    get_content_store,
    resolve_subject_storage_scope,
    run_store_sync,
)
from app.utils.path_helpers import (
    build_docgen_intermediate_latest_dir,
    build_knowledge_build_lock_path,
)
from app.shared.infra.workflow.live_stream import publish_workflow_stream_event
from app.utils.time import ensure_utc_datetime, utcnow

STALE_BUILD_LOCK_TTL = timedelta(minutes=30)
_ACTIVE_BUILD_STATUSES = {"accepted", "running", "publishing"}
_TERMINAL_BUILD_STATUSES = {"completed", "failed", "cancelled", "skipped", "partial_failed"}
_GRAPH_RUNTIME_METRIC_KEYS = {
    "processed_chunks",
    "doc_sync_section_count",
    "doc_sync_llm_section_count",
    "doc_sync_fallback_section_count",
    "doc_sync_question_fallback_section_count",
    "doc_sync_topic_fallback_section_count",
    "doc_sync_unit_changes",
    "doc_sync_edge_changes",
    "doc_sync_elapsed_ms",
    "elapsed_ms",
    "revision_no",
    "last_synced_doc_version_no",
    "knowledge_doc_source",
    "knowledge_doc_chapter_count",
    "graph_input_paths",
    "source_ref_count",
    "backbone_unit_count",
    "backbone_edge_count",
    "stable_anchor_count",
    "deprecated_unit_count",
    "deprecated_edge_count",
}
_GRAPH_RUNTIME_INT_METRIC_KEYS = {
    "processed_chunks",
    "doc_sync_section_count",
    "doc_sync_llm_section_count",
    "doc_sync_fallback_section_count",
    "doc_sync_question_fallback_section_count",
    "doc_sync_topic_fallback_section_count",
    "doc_sync_unit_changes",
    "doc_sync_edge_changes",
    "doc_sync_elapsed_ms",
    "elapsed_ms",
    "revision_no",
    "last_synced_doc_version_no",
    "knowledge_doc_chapter_count",
    "source_ref_count",
    "backbone_unit_count",
    "backbone_edge_count",
    "stable_anchor_count",
    "deprecated_unit_count",
    "deprecated_edge_count",
}

_STAGE_PROGRESS = {
    "idle": 0,
    "build_accepted": 8,
    "prepare_shared": 18,
    "planner_confirmed": 22,
    "preparing_docgen_global_seed": 28,
    "preparing_docgen_context": 30,
    "dispatch_ready": 34,
    "backbone_seed_ready": 36,
    "building_document_backbone": 38,
    "preparing_chapter_execution_briefs": 42,
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
    "queued_after_docgen": 92,
    "graph_docs_sync": 94,
    "graph_file_ingest": 96,
    "publishing": 97,
    "docgen_finalized": 97,
    "completed": 100,
    "disabled": 100,
    "blocked_by_docgen_failure": 0,
    "failed": 0,
    "cancelled": 0,
}

_STAGE_DESCRIPTION = {
    "idle": "当前没有正在进行的知识文档构建任务。",
    "build_accepted": "已接收构建请求，等待启动。",
    "prepare_shared": "正在准备共享资料上下文。",
    "planner_confirmed": "构建方案已确认，准备按章节启动。",
    "preparing_docgen_global_seed": "正在准备 DocGen 全局种子：文档意图与文件摘要。",
    "preparing_docgen_context": "正在增强大纲、识别写作意图并摘要材料。",
    "dispatch_ready": "章节执行计划 seed 已生成，准备构建知识骨架。",
    "backbone_seed_ready": "骨架 seed 已确认，准备构建整本文档知识骨架。",
    "building_document_backbone": "正在统一术语、主张、证据和易混点。",
    "preparing_chapter_execution_briefs": "文档知识骨架已生成，正在并行准备章节执行 brief。",
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
    "queued_after_docgen": "知识文档发布后将自动开始图谱同步。",
    "graph_docs_sync": "正在从知识文档同步知识点、知识图像和关系。",
    "graph_file_ingest": "正在从已解析文件抽取候选并构建图谱。",
    "publishing": "正在发布最终知识文档。",
    "docgen_finalized": "知识文档已发布，正在收口运行状态。",
    "completed": "知识文档构建完成。",
    "disabled": "已关闭文档构建后自动图谱同步。",
    "blocked_by_docgen_failure": "知识文档构建失败，未继续图谱同步。",
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
    build_group_id: str | None = None
    source_file_ids: list[int] = Field(default_factory=list)
    prompt: str | None = None


class KnowledgeBuildRuntimeStatus(BaseModel):
    """Runtime metadata for the current or most recent build."""

    requested_at: datetime
    build_kind: str = "docgen"
    build_group_id: str | None = None
    status: str = "accepted"
    stage: str = "build_accepted"
    started_at: datetime | None = None
    finished_at: datetime | None = None
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
    doc_sync_section_count: int = 0
    doc_sync_llm_section_count: int = 0
    doc_sync_fallback_section_count: int = 0
    doc_sync_question_fallback_section_count: int = 0
    doc_sync_topic_fallback_section_count: int = 0
    sample_cards: list[dict[str, str]] = Field(default_factory=list)
    mode_reason: str | None = None
    plan_summary: str | None = None
    metrics: dict[str, object] = Field(default_factory=dict)
    chapter_progress: list[dict[str, object]] = Field(default_factory=list)
    chapter_previews: list[dict[str, object]] = Field(default_factory=list)
    merge_preview: dict[str, object] = Field(default_factory=dict)
    recent_events: list[dict[str, object]] = Field(default_factory=list)


class KnowledgeBuildRuntimeEnvelope(BaseModel):
    """Persisted runtime envelope for aggregate/docgen/graph lanes."""

    build_group_id: str | None = None
    docgen_runtime: KnowledgeBuildRuntimeStatus | None = None
    graph_runtime: KnowledgeBuildRuntimeStatus | None = None


def _get_status_lock(subject: str) -> RLock:
    with _STATUS_LOCK_GUARD:
        lock = _STATUS_LOCKS.get(subject)
        if lock is None:
            lock = RLock()
            _STATUS_LOCKS[subject] = lock
        return lock


def _normalize_build_lane(build_kind: str | None) -> Literal["docgen", "graph"]:
    return "graph" if str(build_kind or "").strip().lower() == "graph" else "docgen"


def _lane_attr_name(lane: Literal["docgen", "graph"]) -> str:
    return f"{lane}_runtime"


def sanitize_knowledge_build_error_message(
    error_message: str | None,
    *,
    build_kind: str | None = None,
) -> str | None:
    text = str(error_message or "").strip()
    if not text:
        return None

    lane = _normalize_build_lane(build_kind)
    lane_label = "知识图谱" if lane == "graph" else "知识文档"

    if text == "build_cancelled":
        return f"{lane_label}构建已取消。"
    if text == "build_crashed":
        return f"{lane_label}构建异常失败。"
    if text == "no_ready_digest_inputs":
        return "当前没有可用于图谱构建的已解析资料。"
    if text == "no_graph_build_sources":
        return "当前没有可用于图谱构建的输入来源。"
    if text == "confirmed_plan_required":
        return "知识文档构建必须基于已确认的构建方案执行，请先完成 planner 确认。"
    if (
        "Dimension mismatch" in text
        or "sqlite3.OperationalError" in text
        or ("chunk_embeddings" in text and "embedding" in text)
    ):
        return "Embedding 配置已变化，请先重建向量后再继续。"
    if "[SQL:" in text or "parameters:" in text or "Traceback" in text or len(text) > 240:
        return f"{lane_label}构建异常失败。"
    return text


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


def _normalize_chapter_preview_entry(entry: dict[str, object]) -> dict[str, object]:
    chapter_index = int(entry.get("chapter_index", 0) or 0)
    fallback_title = f"第 {chapter_index} 章" if chapter_index > 0 else "未命名章节"
    title = str(entry.get("title") or fallback_title).strip() or fallback_title
    updated_at = entry.get("updated_at")
    if not isinstance(updated_at, datetime):
        updated_at = None
    return {
        "chapter_index": chapter_index,
        "title": title,
        "status": str(entry.get("status") or "planned").strip() or "planned",
        "excerpt": str(entry.get("excerpt") or "").strip(),
        "latest_headings": _normalize_compact_string_list(entry.get("latest_headings"), limit=6),
        "word_count": int(entry.get("word_count", 0) or 0),
        "source_count": int(entry.get("source_count", 0) or 0),
        "updated_at": updated_at,
    }


def _normalize_merge_preview_entry(entry: dict[str, object]) -> dict[str, object]:
    latest_chapter_titles = _normalize_compact_string_list(entry.get("latest_chapter_titles"), limit=8)
    draft_excerpt = str(entry.get("draft_excerpt") or "").strip()
    updated_at = entry.get("updated_at")
    if not isinstance(updated_at, datetime):
        updated_at = None
    return {
        "latest_chapter_titles": latest_chapter_titles,
        "draft_excerpt": draft_excerpt,
        "updated_at": updated_at,
    }


def _coerce_graph_metric_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _normalize_graph_runtime_metrics(status: KnowledgeBuildRuntimeStatus) -> KnowledgeBuildRuntimeStatus:
    metrics = dict(status.metrics or {})
    legacy_values = {
        "processed_chunks": status.processed_chunks,
        "doc_sync_section_count": status.doc_sync_section_count,
        "doc_sync_llm_section_count": status.doc_sync_llm_section_count,
        "doc_sync_fallback_section_count": status.doc_sync_fallback_section_count,
        "doc_sync_question_fallback_section_count": status.doc_sync_question_fallback_section_count,
        "doc_sync_topic_fallback_section_count": status.doc_sync_topic_fallback_section_count,
    }
    for key, value in legacy_values.items():
        if key not in metrics or metrics.get(key) in (None, ""):
            metrics[key] = value

    if "elapsed_ms" not in metrics and "doc_sync_elapsed_ms" in metrics:
        metrics["elapsed_ms"] = metrics.get("doc_sync_elapsed_ms")

    for key in _GRAPH_RUNTIME_INT_METRIC_KEYS:
        metrics[key] = _coerce_graph_metric_int(metrics.get(key))

    status.processed_chunks = _coerce_graph_metric_int(metrics.get("processed_chunks"))
    status.doc_sync_section_count = _coerce_graph_metric_int(metrics.get("doc_sync_section_count"))
    status.doc_sync_llm_section_count = _coerce_graph_metric_int(metrics.get("doc_sync_llm_section_count"))
    status.doc_sync_fallback_section_count = _coerce_graph_metric_int(metrics.get("doc_sync_fallback_section_count"))
    status.doc_sync_question_fallback_section_count = _coerce_graph_metric_int(metrics.get("doc_sync_question_fallback_section_count"))
    status.doc_sync_topic_fallback_section_count = _coerce_graph_metric_int(metrics.get("doc_sync_topic_fallback_section_count"))
    status.metrics = metrics
    return status


def _merge_graph_runtime_metrics(
    existing: KnowledgeBuildRuntimeStatus,
    payload: dict[str, object],
) -> dict[str, object]:
    metrics = dict(existing.metrics or {})
    incoming_metrics = payload.get("metrics")
    if isinstance(incoming_metrics, dict):
        metrics.update(incoming_metrics)

    for key in _GRAPH_RUNTIME_METRIC_KEYS:
        if key in payload:
            metrics[key] = payload[key]

    if "elapsed_ms" not in metrics and "doc_sync_elapsed_ms" in metrics:
        metrics["elapsed_ms"] = metrics.get("doc_sync_elapsed_ms")

    for key in _GRAPH_RUNTIME_INT_METRIC_KEYS:
        metrics[key] = _coerce_graph_metric_int(metrics.get(key))

    return metrics


def _derive_progress_from_chapters(status: KnowledgeBuildRuntimeStatus) -> int:
    chapters = [
        _normalize_chapter_progress_entry(dict(item))
        for item in list(status.chapter_progress or [])
    ]
    if not chapters:
        return int(status.progress_pct or 0)

    stage = str(status.stage or "").strip()
    total = len(chapters)
    statuses = {str(item.get("status") or "").strip() for item in chapters}
    generated_or_later = {"generated", "enhancing", "enhanced", "reviewing", "reviewed"}
    enhanced_or_later = {"enhanced", "reviewing", "reviewed"}

    if stage == "generating_chapters":
        done = sum(1 for item in chapters if str(item.get("status") or "") in generated_or_later)
        return 48 + int((done / total) * 16)
    if stage == "enhancing_chapters" or "enhancing" in statuses:
        done = sum(1 for item in chapters if str(item.get("status") or "") in enhanced_or_later)
        return 64 + int((done / total) * 8)
    if stage == "reviewing_content" or "reviewing" in statuses:
        done = sum(1 for item in chapters if str(item.get("status") or "") == "reviewed")
        return 76 + int((done / total) * 4)

    return int(status.progress_pct or 0)


def _hydrate_runtime_status(status: KnowledgeBuildRuntimeStatus) -> KnowledgeBuildRuntimeStatus:
    status.requested_at = ensure_utc_datetime(status.requested_at) or utcnow()
    status.started_at = ensure_utc_datetime(status.started_at) or status.requested_at
    status.finished_at = ensure_utc_datetime(status.finished_at)
    status.build_kind = str(status.build_kind or "docgen").strip() or "docgen"
    status.metrics = dict(status.metrics or {})
    is_graph_lane = _normalize_build_lane(status.build_kind) == "graph"
    if is_graph_lane:
        status = _normalize_graph_runtime_metrics(status)
    if not status.current_stage_description:
        status.current_stage_description = _STAGE_DESCRIPTION.get(status.stage, "知识文档构建进行中。")

    stage_progress = _STAGE_PROGRESS.get(status.stage)
    if status.status == "completed":
        status.progress_pct = 100
    elif stage_progress is not None:
        status.progress_pct = max(int(status.progress_pct), int(stage_progress))
    status.progress_pct = max(int(status.progress_pct), _derive_progress_from_chapters(status))
    status.progress_pct = max(0, min(int(status.progress_pct), 100))

    if status.current_chunk is None and status.processed_chunks > 0:
        status.current_chunk = status.processed_chunks
    if status.status == "completed" and status.total_chunks > 0:
        status.current_chunk = status.total_chunks
        status.processed_chunks = status.total_chunks
        if is_graph_lane:
            status.metrics["processed_chunks"] = max(
                _coerce_graph_metric_int(status.metrics.get("processed_chunks")),
                status.processed_chunks,
            )

    if status.status == "completed":
        status.estimated_remaining_seconds = 0
        status.finished_at = status.finished_at or utcnow()
    elif status.status in {"failed", "cancelled", "skipped", "partial_failed"}:
        status.estimated_remaining_seconds = None
        status.finished_at = status.finished_at or utcnow()
    elif status.status == "idle":
        status.estimated_remaining_seconds = None
    elif 0 < status.progress_pct < 100:
        elapsed_seconds = max(1, int((utcnow() - status.requested_at).total_seconds()))
        remaining = int(elapsed_seconds * (100 - status.progress_pct) / max(status.progress_pct, 1))
        status.estimated_remaining_seconds = max(3, remaining)
    else:
        status.estimated_remaining_seconds = None
        if status.status in _ACTIVE_BUILD_STATUSES:
            status.finished_at = None

    status.chapter_progress = [
        _normalize_chapter_progress_entry(dict(item))
        for item in list(status.chapter_progress or [])
    ]
    status.chapter_progress.sort(key=lambda item: int(item.get("chapter_index", 0) or 0))
    status.chapter_previews = [
        _normalize_chapter_preview_entry(dict(item))
        for item in list(status.chapter_previews or [])
        if int(dict(item).get("chapter_index", 0) or 0) > 0
    ]
    status.chapter_previews.sort(key=lambda item: int(item.get("chapter_index", 0) or 0))
    status.merge_preview = (
        _normalize_merge_preview_entry(dict(status.merge_preview or {}))
        if dict(status.merge_preview or {})
        else {}
    )
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


def _hydrate_runtime_envelope(
    envelope: KnowledgeBuildRuntimeEnvelope,
) -> KnowledgeBuildRuntimeEnvelope:
    if envelope.docgen_runtime is not None:
        envelope.docgen_runtime = _hydrate_runtime_status(envelope.docgen_runtime)
    if envelope.graph_runtime is not None:
        envelope.graph_runtime = _hydrate_runtime_status(envelope.graph_runtime)
    envelope.build_group_id = (
        envelope.build_group_id
        or (envelope.docgen_runtime.build_group_id if envelope.docgen_runtime is not None else None)
        or (envelope.graph_runtime.build_group_id if envelope.graph_runtime is not None else None)
    )
    return envelope


def _build_runtime_metrics(
    *,
    docgen_runtime: KnowledgeBuildRuntimeStatus | None,
    graph_runtime: KnowledgeBuildRuntimeStatus | None,
) -> dict[str, object]:
    return {
        "docgen_status": (docgen_runtime.status if docgen_runtime is not None else "idle"),
        "graph_status": (graph_runtime.status if graph_runtime is not None else "idle"),
    }


def build_aggregate_knowledge_build_status(
    envelope: KnowledgeBuildRuntimeEnvelope | None,
) -> KnowledgeBuildRuntimeStatus | None:
    if envelope is None:
        return None

    hydrated = _hydrate_runtime_envelope(envelope)
    docgen_runtime = hydrated.docgen_runtime
    graph_runtime = hydrated.graph_runtime
    build_group_id = hydrated.build_group_id

    if docgen_runtime is None and graph_runtime is None:
        return None

    def _new(
        *,
        requested_at: datetime,
        status: str,
        stage: str,
        description: str,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        error_message: str | None = None,
        progress_pct: int = 0,
    ) -> KnowledgeBuildRuntimeStatus:
        return _hydrate_runtime_status(
            KnowledgeBuildRuntimeStatus(
                requested_at=requested_at,
                build_kind="aggregate",
                build_group_id=build_group_id,
                status=status,
                stage=stage,
                started_at=started_at,
                finished_at=finished_at,
                error_message=error_message,
                progress_pct=progress_pct,
                current_stage_description=description,
                metrics=_build_runtime_metrics(
                    docgen_runtime=docgen_runtime,
                    graph_runtime=graph_runtime,
                ),
            )
        )

    if docgen_runtime is None:
        return _new(
            requested_at=graph_runtime.requested_at,
            status=graph_runtime.status,
            stage=graph_runtime.stage,
            description=graph_runtime.current_stage_description or "知识图谱构建进行中。",
            started_at=graph_runtime.started_at,
            finished_at=graph_runtime.finished_at,
            error_message=graph_runtime.error_message,
            progress_pct=graph_runtime.progress_pct,
        )

    if docgen_runtime.status in {"failed", "cancelled"}:
        return _new(
            requested_at=docgen_runtime.requested_at,
            status=docgen_runtime.status,
            stage=docgen_runtime.stage,
            description=docgen_runtime.current_stage_description or "知识文档构建失败。",
            started_at=docgen_runtime.started_at,
            finished_at=docgen_runtime.finished_at,
            error_message=docgen_runtime.error_message,
            progress_pct=docgen_runtime.progress_pct,
        )

    if docgen_runtime.status in _ACTIVE_BUILD_STATUSES:
        return _new(
            requested_at=docgen_runtime.requested_at,
            status="running",
            stage=docgen_runtime.stage,
            description=docgen_runtime.current_stage_description or "知识文档构建进行中。",
            started_at=docgen_runtime.started_at,
            progress_pct=docgen_runtime.progress_pct,
        )

    if graph_runtime is None:
        return _new(
            requested_at=docgen_runtime.requested_at,
            status=docgen_runtime.status,
            stage=docgen_runtime.stage,
            description=docgen_runtime.current_stage_description or "知识文档已发布。",
            started_at=docgen_runtime.started_at,
            finished_at=docgen_runtime.finished_at,
            progress_pct=docgen_runtime.progress_pct,
        )

    if graph_runtime.status in _ACTIVE_BUILD_STATUSES:
        return _new(
            requested_at=docgen_runtime.requested_at,
            status="running",
            stage=graph_runtime.stage,
            description=graph_runtime.current_stage_description or "知识图谱构建进行中。",
            started_at=docgen_runtime.started_at,
            progress_pct=max(docgen_runtime.progress_pct, graph_runtime.progress_pct),
        )

    if graph_runtime.status in {"failed", "cancelled"}:
        return _new(
            requested_at=docgen_runtime.requested_at,
            status="partial_failed",
            stage=graph_runtime.stage,
            description=graph_runtime.current_stage_description or "知识文档已发布，但图谱构建失败。",
            started_at=docgen_runtime.started_at,
            finished_at=graph_runtime.finished_at or docgen_runtime.finished_at,
            error_message=graph_runtime.error_message,
            progress_pct=100,
        )

    if graph_runtime.status == "skipped":
        return _new(
            requested_at=docgen_runtime.requested_at,
            status="completed",
            stage="completed",
            description=graph_runtime.current_stage_description or docgen_runtime.current_stage_description or "知识文档已发布。",
            started_at=docgen_runtime.started_at,
            finished_at=docgen_runtime.finished_at,
            progress_pct=100,
        )

    return _new(
        requested_at=docgen_runtime.requested_at,
        status="completed",
        stage="completed",
        description=graph_runtime.current_stage_description or "知识文档与知识图谱已完成。",
        started_at=docgen_runtime.started_at,
        finished_at=graph_runtime.finished_at or docgen_runtime.finished_at,
        progress_pct=100,
    )


def _read_legacy_knowledge_build_status(subject: str) -> KnowledgeBuildRuntimeStatus | None:
    cs = get_content_store()
    key = resolve_subject_storage_scope(subject).build_status_key()
    status = run_store_sync(cs.read_json, key, KnowledgeBuildRuntimeStatus)
    return _hydrate_runtime_status(status) if status is not None else None


def _write_legacy_knowledge_build_status(subject: str, status: KnowledgeBuildRuntimeStatus) -> str:
    cs = get_content_store()
    key = resolve_subject_storage_scope(subject).build_status_key()
    run_store_sync(cs.write_json, key, status)
    return key


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


def read_knowledge_build_runtime(subject: str) -> KnowledgeBuildRuntimeEnvelope | None:
    """Read the unified runtime envelope for one subject."""

    cs = get_content_store()
    key = resolve_subject_storage_scope(subject).build_runtime_key()
    runtime = run_store_sync(cs.read_json, key, KnowledgeBuildRuntimeEnvelope)
    if runtime is not None:
        return _hydrate_runtime_envelope(runtime)

    legacy = _read_legacy_knowledge_build_status(subject)
    if legacy is None:
        return None
    return _hydrate_runtime_envelope(
        KnowledgeBuildRuntimeEnvelope(
            build_group_id=legacy.build_group_id,
            docgen_runtime=legacy,
        )
    )


def write_knowledge_build_runtime(subject: str, runtime: KnowledgeBuildRuntimeEnvelope) -> str:
    """Persist the unified runtime envelope for one subject."""

    cs = get_content_store()
    key = resolve_subject_storage_scope(subject).build_runtime_key()
    run_store_sync(cs.write_json, key, _hydrate_runtime_envelope(runtime))
    publish_workflow_stream_event(subject, "runtime_dirty", {"reason": "runtime_write"})
    return key


def read_knowledge_build_status(subject: str) -> KnowledgeBuildRuntimeStatus | None:
    """Read the legacy docgen runtime payload used by docs-oriented polling."""

    runtime = read_knowledge_build_runtime(subject)
    if runtime is not None and runtime.docgen_runtime is not None:
        return runtime.docgen_runtime
    return _read_legacy_knowledge_build_status(subject)


def write_knowledge_build_status(subject: str, status: KnowledgeBuildRuntimeStatus) -> str:
    """Persist the legacy docgen runtime payload."""

    return _write_legacy_knowledge_build_status(subject, _hydrate_runtime_status(status))


def read_knowledge_build_aggregate_status(subject: str) -> KnowledgeBuildRuntimeStatus | None:
    """Read the aggregate runtime status for one subject."""

    return build_aggregate_knowledge_build_status(read_knowledge_build_runtime(subject))


def update_knowledge_build_lane_status(
    subject: str,
    *,
    lane: Literal["docgen", "graph"],
    **kwargs: object,
) -> KnowledgeBuildRuntimeStatus:
    """Merge updates into one runtime lane and refresh the persisted envelope."""

    with _get_status_lock(subject):
        runtime = read_knowledge_build_runtime(subject) or KnowledgeBuildRuntimeEnvelope()
        attr_name = _lane_attr_name(lane)
        existing = getattr(runtime, attr_name)
        requested_at = kwargs.get("requested_at")
        normalized_requested_at = ensure_utc_datetime(requested_at) if isinstance(requested_at, datetime) else None
        build_group_id = str(kwargs.get("build_group_id") or "").strip() or None

        should_reset = (
            existing is None
            or (normalized_requested_at is not None and existing.requested_at != normalized_requested_at)
            or (build_group_id is not None and existing is not None and existing.build_group_id != build_group_id)
        )
        if should_reset:
            existing = KnowledgeBuildRuntimeStatus(
                requested_at=normalized_requested_at or utcnow(),
                build_kind=lane,
                build_group_id=build_group_id,
            )

        payload = dict(kwargs)
        payload["build_kind"] = lane
        if "error_message" in payload:
            payload["error_message"] = sanitize_knowledge_build_error_message(
                payload.get("error_message"),
                build_kind=lane,
            )
        if lane == "graph":
            payload["metrics"] = _merge_graph_runtime_metrics(existing, payload)
            runtime_fields = set(KnowledgeBuildRuntimeStatus.model_fields)
            for key in list(payload.keys()):
                if key in _GRAPH_RUNTIME_METRIC_KEYS and key not in runtime_fields:
                    payload.pop(key, None)

        updated = existing.model_copy(update=payload)
        updated = _hydrate_runtime_status(updated)
        setattr(runtime, attr_name, updated)
        runtime.build_group_id = (
            build_group_id
            or updated.build_group_id
            or runtime.build_group_id
        )
        runtime = _hydrate_runtime_envelope(runtime)
        write_knowledge_build_runtime(subject, runtime)

        if lane == "docgen":
            write_knowledge_build_status(subject, updated)

        return updated


def update_knowledge_build_status(subject: str, **kwargs: object) -> KnowledgeBuildRuntimeStatus:
    """Merge updates into the runtime build-status payload."""

    lane = _normalize_build_lane(str(kwargs.get("build_kind") or "docgen"))
    return update_knowledge_build_lane_status(subject, lane=lane, **kwargs)


def upsert_knowledge_build_chapter_progress(
    subject: str,
    *,
    chapter_progress: dict[str, object],
    requested_at: datetime | None = None,
) -> KnowledgeBuildRuntimeStatus:
    """Merge one chapter progress entry into the runtime build status."""

    with _get_status_lock(subject):
        runtime = read_knowledge_build_runtime(subject) or KnowledgeBuildRuntimeEnvelope()
        existing = runtime.docgen_runtime
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
        existing.build_kind = "docgen"
        existing = _hydrate_runtime_status(existing)
        runtime.docgen_runtime = existing
        runtime.build_group_id = runtime.build_group_id or existing.build_group_id
        write_knowledge_build_runtime(subject, runtime)
        write_knowledge_build_status(subject, existing)
        return existing


def upsert_knowledge_build_chapter_preview(
    subject: str,
    *,
    chapter_preview: dict[str, object],
    requested_at: datetime | None = None,
) -> KnowledgeBuildRuntimeStatus:
    """Merge one chapter preview entry into the runtime build status."""

    with _get_status_lock(subject):
        runtime = read_knowledge_build_runtime(subject) or KnowledgeBuildRuntimeEnvelope()
        existing = runtime.docgen_runtime
        if existing is None:
            existing = KnowledgeBuildRuntimeStatus(requested_at=requested_at or utcnow())
        chapter_index = int(chapter_preview.get("chapter_index", 0) or 0)
        if chapter_index <= 0:
            existing = _hydrate_runtime_status(existing)
            runtime.docgen_runtime = existing
            runtime.build_group_id = runtime.build_group_id or existing.build_group_id
            write_knowledge_build_runtime(subject, runtime)
            write_knowledge_build_status(subject, existing)
            return existing
        current = {
            int(item.get("chapter_index", 0) or 0): dict(item)
            for item in list(existing.chapter_previews or [])
        }
        merged = dict(current.get(chapter_index, {}))
        merged.update(dict(chapter_preview))
        merged["updated_at"] = chapter_preview.get("updated_at") if "updated_at" in chapter_preview else utcnow()
        current[chapter_index] = _normalize_chapter_preview_entry(merged)
        existing.chapter_previews = [current[key] for key in sorted(current)]
        existing.build_kind = "docgen"
        existing = _hydrate_runtime_status(existing)
        runtime.docgen_runtime = existing
        runtime.build_group_id = runtime.build_group_id or existing.build_group_id
        write_knowledge_build_runtime(subject, runtime)
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
        runtime = read_knowledge_build_runtime(subject) or KnowledgeBuildRuntimeEnvelope()
        existing = runtime.docgen_runtime
        if existing is None:
            existing = KnowledgeBuildRuntimeStatus(requested_at=requested_at or utcnow())
        normalized = _normalize_recent_event_entry(event)
        existing.recent_events = [normalized, *list(existing.recent_events or [])][: max(1, int(limit))]
        existing.build_kind = "docgen"
        existing = _hydrate_runtime_status(existing)
        runtime.docgen_runtime = existing
        runtime.build_group_id = runtime.build_group_id or existing.build_group_id
        write_knowledge_build_runtime(subject, runtime)
        write_knowledge_build_status(subject, existing)
        publish_workflow_stream_event(subject, "build_event", normalized)
        return existing


def update_knowledge_build_merge_preview(
    subject: str,
    *,
    merge_preview: dict[str, object],
    requested_at: datetime | None = None,
) -> KnowledgeBuildRuntimeStatus:
    """Merge whole-document preview content into the runtime build status."""

    with _get_status_lock(subject):
        runtime = read_knowledge_build_runtime(subject) or KnowledgeBuildRuntimeEnvelope()
        existing = runtime.docgen_runtime
        if existing is None:
            existing = KnowledgeBuildRuntimeStatus(requested_at=requested_at or utcnow())
        current = dict(existing.merge_preview or {})
        current.update(dict(merge_preview))
        current["updated_at"] = merge_preview.get("updated_at") if "updated_at" in merge_preview else utcnow()
        existing.merge_preview = _normalize_merge_preview_entry(current)
        existing.build_kind = "docgen"
        existing = _hydrate_runtime_status(existing)
        runtime.docgen_runtime = existing
        runtime.build_group_id = runtime.build_group_id or existing.build_group_id
        write_knowledge_build_runtime(subject, runtime)
        write_knowledge_build_status(subject, existing)
        return existing


def clear_knowledge_build_status(subject: str) -> None:
    """Remove runtime build-status metadata."""

    cs = get_content_store()
    run_store_sync(cs.delete, resolve_subject_storage_scope(subject).build_status_key(), default=None)
    run_store_sync(cs.delete, resolve_subject_storage_scope(subject).build_runtime_key(), default=None)


def read_knowledge_manifest(subject: str) -> KnowledgeDocsManifest | None:
    """Read the published manifest if it exists."""

    cs = get_content_store()
    return run_store_sync(
        cs.read_json,
        resolve_subject_storage_scope(subject).build_manifest_key(),
        KnowledgeDocsManifest,
    )


def write_knowledge_manifest(subject: str, manifest: KnowledgeDocsManifest) -> str:
    """Persist the published manifest."""

    cs = get_content_store()
    key = resolve_subject_storage_scope(subject).build_manifest_key()
    run_store_sync(cs.write_json, key, manifest)
    return key


def clear_docgen_staging(subject: str) -> None:
    """Remove the current knowledge-markdown build directory."""

    cs = get_content_store()
    run_store_sync(cs.delete_prefix, resolve_subject_storage_scope(subject).knowledge_build_prefix(), default=0)

    if is_local_mode():
        intermediate_dir = build_docgen_intermediate_latest_dir(subject)
        if intermediate_dir.exists():
            shutil.rmtree(intermediate_dir, ignore_errors=True)


def clear_published_knowledge_docs_files(subject: str) -> None:
    """Remove all published knowledge-doc files, including archived versions."""

    cs = get_content_store()
    subject_scope = resolve_subject_storage_scope(subject)
    prefix = subject_scope.knowledge_doc_key("")
    keys = run_store_sync(cs.list_prefix, prefix, default=[])
    for key in keys:
        relative = key.removeprefix(prefix)
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
    subject_scope = resolve_subject_storage_scope(subject)
    prefix = subject_scope.knowledge_doc_key("")
    keys = run_store_sync(cs.list_prefix, prefix, default=[])
    for key in keys:
        relative = key.removeprefix(prefix)
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
    run_store_sync(cs.delete, resolve_subject_storage_scope(subject).build_manifest_key(), default=None)

    release_knowledge_build_lock(subject)


__all__ = [
    "KnowledgeBuildLock",
    "KnowledgeBuildRuntimeEnvelope",
    "KnowledgeBuildRuntimeStatus",
    "KnowledgeDocsManifest",
    "STALE_BUILD_LOCK_TTL",
    "acquire_knowledge_build_lock",
    "append_knowledge_build_recent_event",
    "build_aggregate_knowledge_build_status",
    "clear_current_published_knowledge_docs_files",
    "clear_docgen_staging",
    "clear_knowledge_build_status",
    "clear_knowledge_runtime_artifacts",
    "clear_published_knowledge_docs_files",
    "is_knowledge_build_locked",
    "read_knowledge_build_lock",
    "read_knowledge_build_runtime",
    "read_knowledge_build_aggregate_status",
    "read_knowledge_build_status",
    "read_knowledge_manifest",
    "release_knowledge_build_lock",
    "sanitize_knowledge_build_error_message",
    "update_knowledge_build_lane_status",
    "update_knowledge_build_merge_preview",
    "update_knowledge_build_status",
    "upsert_knowledge_build_chapter_preview",
    "upsert_knowledge_build_chapter_progress",
    "write_knowledge_build_runtime",
    "write_knowledge_build_status",
    "write_knowledge_manifest",
]
