"""DocGen build lifecycle around the graph runtime.

This module owns the API-facing lifecycle around one DocGen request:
file selection, confirmed-plan loading, build locking, background
execution, runtime polling, and result assembly.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from contextlib import nullcontext
from datetime import datetime
from time import perf_counter
from typing import Any

import structlog
from sqlmodel import Session, select

from app.models.build_planner import ConfirmedBuildPlan
from app.models.raw_file import RawFile
from app.models.course import Course
from app.models.knowledge_graph_sync import KnowledgeGraphSyncRun
from app.repositories.files_repo import list_all_raw_files_by_course, list_raw_files_by_ids
from app.repositories.knowledge.docgen_repo import get_current_published_docs
from app.repositories.knowledge.knowledge_repo import clear_chunk_vector_metadata
from app.schemas.knowledge import (
    BuildPreviewChapterPreviewResponse,
    BuildPreviewChapterProgressResponse,
    BuildPreviewMergePreviewResponse,
    BuildPreviewNodeResponse,
    BuildPreviewRecentEventResponse,
    DocGenBuildData,
    DocGenGetResponse,
    KnowledgeBuildLaneRuntimeResponse,
    KnowledgeGraphBuildMetricsResponse,
    KnowledgeBuildMetricsResponse,
    KnowledgeBuildPreviewResponse,
    KnowledgeBuildRuntimeResponse,
    KnowledgeBuildStatusResponse,
    CourseVectorStatusResponse,
)
from app.shared.infra.database import managed_session
from app.shared.infra.exceptions import (
    ConfirmedBuildPlanRequiredError,
    NoReadyFilesForDocGenError,
    CourseBuildLockConflictError,
)
from app.shared.infra.knowledge.build_store import (
    KnowledgeBuildLock,
    acquire_knowledge_build_lock,
    build_aggregate_knowledge_build_status,
    clear_docgen_staging,
    read_knowledge_build_lock,
    read_knowledge_build_runtime,
    read_knowledge_manifest,
    sanitize_knowledge_build_error_message,
    update_knowledge_build_lane_status,
)
from app.shared.infra.llm_support.model_choices import normalize_runtime_model_override
from app.shared.infra.observability.trace import (
    langsmith_trace,
    sanitize_langsmith_input,
    sanitize_langsmith_output,
)
from app.shared.infra.settings import get_settings
from app.shared.infra.storage import (
    CourseStorageScope,
    build_course_storage_scope,
    get_content_store,
    resolve_course_storage_scope,
    run_store_sync,
)
from app.shared.infra.course import (
    get_course_vector_status_by_id,
    inspect_course_build_precheck,
    resolve_course_build_vector_status,
)
from app.shared.infra.tools.builtin.markdown_processing import normalize_markdown_rendering, normalize_mermaid_blocks
from app.utils.presenters import require_id
from app.utils.time import utcnow
from app.workflows.digest.common.contracts import normalize_digest_confirmed_plan_payload
from app.workflows.digest.common.file_status import is_markdown_ready_for_digest
from app.workflows.digest.common.metrics import build_token_summary
from app.workflows.digest.docgen.lib.interactive_overlays import (
    apply_interactive_overlays_to_markdown,
    load_current_interactive_overlays,
)
from app.workflows.digest.docgen.lib.public_markdown import sanitize_public_markdown
from app.workflows.digest.planner import (
    get_confirmed_build_plan,
    mark_confirmed_build_plan_status,
)

logger = structlog.get_logger()


def _clean_prompt(prompt: str | None) -> str | None:
    prompt = (prompt or "").strip()
    return prompt or None


def _select_ready_docgen_files_by_ids(
    session: Session,
    *,
    course_id: str,
    file_ids: list[str],
    allow_empty: bool = False,
) -> tuple[list[RawFile], int]:
    all_files = list_all_raw_files_by_course(session, course_id)
    ready_files = [item for item in all_files if item.id and is_markdown_ready_for_digest(item)]
    ready_ids = {require_id(item.id, "RawFile.id") for item in ready_files}
    requested = {
        require_id(item.id, "RawFile.id"): item
        for item in list_raw_files_by_ids(session, course_id, file_ids)
        if item.id
    }
    accepted = [requested[file_id] for file_id in file_ids if file_id in requested and file_id in ready_ids]
    if not accepted and not allow_empty:
        raise NoReadyFilesForDocGenError(course_id)
    return accepted, len(ready_files)


def _resolve_file_ids(raw_files: list[RawFile]) -> list[str]:
    return [require_id(item.id, "RawFile.id") for item in raw_files]


def _new_build_session_id() -> str:
    return uuid.uuid4().hex


def _session_context(session: Session | None):
    return nullcontext(session) if session is not None else managed_session()


def _clear_docgen_staging_safely(
    course_id: str,
    *,
    course_scope: CourseStorageScope | None = None,
) -> None:
    try:
        clear_docgen_staging(course_id, course_scope=course_scope)
    except Exception:
        logger.exception("knowledge_build_cleanup_failed", course_id=course_id)


def _write_docgen_status(
    course_id: str,
    *,
    requested_at: datetime,
    status: str,
    stage: str,
    course_scope: CourseStorageScope | None = None,
    **extra: object,
) -> None:
    update_knowledge_build_lane_status(
        course_id,
        lane="docgen",
        course_scope=course_scope,
        requested_at=requested_at,
        status=status,
        stage=stage,
        **extra,
    )


def _write_graph_status(
    course_id: str,
    *,
    requested_at: datetime,
    status: str,
    stage: str,
    course_scope: CourseStorageScope | None = None,
    **extra: object,
) -> None:
    update_knowledge_build_lane_status(
        course_id,
        lane="graph",
        course_scope=course_scope,
        requested_at=requested_at,
        status=status,
        stage=stage,
        **extra,
    )


def _mark_confirmed_plan_status(
    *,
    course_id: str,
    user_id: str,
    confirmed_plan_id: str,
    status: str,
) -> None:
    with managed_session() as session:
        mark_confirmed_build_plan_status(
            session,
            course_id=course_id,
            user_id=user_id,
            plan_id=confirmed_plan_id,
            status=status,
        )


def _extract_markdown_excerpt(markdown: str, *, max_lines: int = 6, max_chars: int = 420) -> str:
    lines: list[str] = []
    chars = 0
    for raw_line in markdown.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped == "---":
            continue
        lines.append(stripped)
        chars += len(stripped)
        if len(lines) >= max_lines or chars >= max_chars:
            break
    excerpt = "\n".join(lines).strip()
    return excerpt if len(excerpt) <= max_chars else excerpt[: max_chars - 3].rstrip() + "..."


def _normalize_public_result_markdown(
    markdown: str,
    *,
    allowed_h1_titles: list[str] | None = None,
) -> str:
    text = sanitize_public_markdown(
        normalize_mermaid_blocks(
            normalize_markdown_rendering(str(markdown or "").strip())
        )
    ).strip()
    return _demote_unexpected_public_h1(text, allowed_titles=allowed_h1_titles or []).strip()


def _demote_unexpected_public_h1(markdown: str, *, allowed_titles: list[str]) -> str:
    allowed = {str(title or "").strip() for title in allowed_titles if str(title or "").strip()}
    if not allowed:
        return markdown
    lines = str(markdown or "").splitlines()
    output: list[str] = []
    seen_allowed: set[str] = set()
    in_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            output.append(line)
            continue
        match = re.match(r"^(\s*)#\s+(.+?)\s*$", line)
        if not in_fence and match is not None:
            title = match.group(2).strip()
            if title in allowed and title not in seen_allowed:
                seen_allowed.add(title)
                output.append(line)
                continue
            output.append(f"{match.group(1)}## {title}")
            continue
        output.append(line)
    return "\n".join(output).strip() + ("\n" if output else "")


def _load_current_published_markdown(
    session: Session | None,
    *,
    course_id: str,
    course_scope: CourseStorageScope,
    manifest,
) -> tuple[str, datetime | None]:
    cs = get_content_store()
    manifest_titles = [str(title).strip() for title in list(getattr(manifest, "chapter_titles", []) or []) if str(title).strip()]
    stored_markdown = _normalize_public_result_markdown(
        run_store_sync(
            cs.read_text,
            course_scope.knowledge_doc_key("merged_knowledge_base.md"),
            default="",
        )
        or "",
        allowed_h1_titles=manifest_titles,
    )
    if stored_markdown:
        return stored_markdown, manifest.updated_at if manifest is not None else None

    with _session_context(session) as db_session:
        docs = get_current_published_docs(db_session, course_id)
    parts: list[str] = []
    updated_at: datetime | None = None
    for doc in docs:
        markdown = _normalize_public_result_markdown(
            str(doc.markdown_content or doc.content_markdown or "").strip(),
            allowed_h1_titles=[str(doc.title or "").strip()],
        )
        if markdown:
            parts.append(markdown)
        for candidate in (doc.updated_at, doc.published_at, doc.created_at):
            if candidate is not None and (updated_at is None or candidate > updated_at):
                updated_at = candidate
    return ("\n\n---\n\n".join(parts)).strip(), updated_at


def _resolve_preview_chapter_titles(*, draft_markdown: str, manifest) -> list[str]:
    if manifest is not None and manifest.chapter_titles:
        return [str(title).strip() for title in manifest.chapter_titles[:4] if str(title).strip()]
    titles: list[str] = []
    for raw_line in draft_markdown.splitlines():
        stripped = raw_line.strip()
        if not stripped.startswith("#"):
            continue
        title = stripped.lstrip("#").strip()
        if title and title.lower() not in {"knowledge document overview", "知识文档总览"}:
            titles.append(title)
        if len(titles) >= 4:
            break
    return titles


def _build_initial_chapter_progress(plan: ConfirmedBuildPlan) -> list[dict[str, object]]:
    chapter_contracts = list(plan.chapters or [])
    progress: list[dict[str, object]] = []
    for index, chapter in enumerate(chapter_contracts, start=1):
        chapter_index = int(chapter.get("chapter_index", index) or index)
        progress.append(
            {
                "chapter_index": chapter_index,
                "title": str(chapter.get("title") or f"第 {chapter_index} 章").strip() or f"第 {chapter_index} 章",
                "status": "planned",
                "source_count": 0,
                "local_hits": 0,
                "web_hits": 0,
                "query_count": 0,
                "word_count": 0,
                "fallback_used": False,
            }
        )
    return progress


def _build_preview_sample_nodes(build_status) -> list[BuildPreviewNodeResponse]:
    if build_status is None:
        return []
    nodes: list[BuildPreviewNodeResponse] = []
    for item in build_status.sample_nodes:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        nodes.append(
            BuildPreviewNodeResponse(
                name=name,
                knowledge_unit_type=str(item.get("type", "concept")).strip() or "concept",
            )
        )
        if len(nodes) >= 6:
            break
    return nodes


def _build_preview_sample_cards(build_status) -> list[dict[str, str]]:
    if build_status is None:
        return []
    cards: list[dict[str, str]] = []
    for item in build_status.sample_cards:
        title = str(item.get("title", "")).strip()
        summary = str(item.get("summary", "")).strip()
        if not title or not summary:
            continue
        cards.append(
            {
                "title": title,
                "card_type": str(item.get("card_type", "")).strip() or "topic",
                "summary": summary,
            }
        )
    return cards


def _build_runtime_preview(*, build_status, draft_markdown: str, manifest) -> KnowledgeBuildPreviewResponse | None:
    if build_status is None and not draft_markdown.strip() and manifest is None:
        return None
    sample_nodes = _build_preview_sample_nodes(build_status)
    sample_cards = _build_preview_sample_cards(build_status)
    chapter_progress = [
        BuildPreviewChapterProgressResponse.model_validate(item)
        for item in list(build_status.chapter_progress or [])
    ] if build_status is not None else []
    chapter_previews = [
        BuildPreviewChapterPreviewResponse.model_validate(item)
        for item in list(build_status.chapter_previews or [])
    ] if build_status is not None else []
    recent_events = [
        BuildPreviewRecentEventResponse.model_validate(item)
        for item in list(build_status.recent_events or [])
    ] if build_status is not None else []
    merge_preview_payload = (
        dict(build_status.merge_preview or {})
        if build_status is not None and dict(build_status.merge_preview or {})
        else {}
    )
    fallback_latest_titles = _resolve_preview_chapter_titles(draft_markdown=draft_markdown, manifest=manifest)
    fallback_draft_excerpt = _extract_markdown_excerpt(draft_markdown)
    if fallback_latest_titles and not merge_preview_payload.get("latest_chapter_titles"):
        merge_preview_payload["latest_chapter_titles"] = fallback_latest_titles
    if fallback_draft_excerpt and not merge_preview_payload.get("draft_excerpt"):
        merge_preview_payload["draft_excerpt"] = fallback_draft_excerpt
    merge_preview = (
        BuildPreviewMergePreviewResponse.model_validate(merge_preview_payload)
        if merge_preview_payload
        else None
    )
    latest_chapter_titles = (
        merge_preview.latest_chapter_titles
        if merge_preview is not None
        else fallback_latest_titles
    )
    draft_excerpt = (
        merge_preview.draft_excerpt
        if merge_preview is not None
        else fallback_draft_excerpt
    )
    return KnowledgeBuildPreviewResponse(
        current_stage_description=(build_status.current_stage_description if build_status is not None else None),
        digest_mode=(build_status.digest_mode if build_status is not None else None),
        mode_reason=(build_status.mode_reason if build_status is not None else None),
        processed_chunks=(build_status.processed_chunks if build_status is not None else 0),
        total_chunks=(build_status.total_chunks if build_status is not None else 0),
        doc_sync_section_count=(build_status.doc_sync_section_count if build_status is not None else 0),
        doc_sync_llm_section_count=(build_status.doc_sync_llm_section_count if build_status is not None else 0),
        discovered_node_count=(build_status.discovered_node_count if build_status is not None else 0),
        discovered_node_types=(dict(build_status.discovered_node_types) if build_status is not None else {}),
        sample_nodes=sample_nodes,
        sample_cards=sample_cards,
        plan=(build_status.plan if build_status is not None else None),
        chapter_progress=chapter_progress,
        recent_events=recent_events,
        chapter_previews=chapter_previews,
        merge_preview=merge_preview,
        latest_chapter_titles=latest_chapter_titles,
        draft_excerpt=draft_excerpt,
    )


def _build_runtime_metrics(*, build_status) -> KnowledgeBuildMetricsResponse | None:
    build_session_id = (
        str(build_status.build_session_id).strip()
        if build_status is not None and build_status.build_session_id is not None
        else ""
    )
    if not build_session_id:
        return None
    token_summary = build_token_summary(build_session_id=build_session_id)
    if token_summary.total_calls <= 0 and token_summary.failed_call_count <= 0:
        return None
    lane_counts = {
        lane: count
        for lane, count in token_summary.call_count_by_lane.items()
        if lane and lane != "(unknown_lane)" and count > 0
    }
    return KnowledgeBuildMetricsResponse(
        llm_total_calls=token_summary.total_calls,
        failed_llm_call_count=token_summary.failed_call_count,
        llm_avg_latency_ms=token_summary.avg_latency_ms,
        call_count_by_lane=lane_counts,
    )


def _build_graph_metrics(*, build_status) -> KnowledgeGraphBuildMetricsResponse:
    if build_status is None:
        return KnowledgeGraphBuildMetricsResponse()
    return KnowledgeGraphBuildMetricsResponse.model_validate(dict(build_status.metrics or {}))


def _int_metric(metrics: dict[str, Any], *keys: str) -> int:
    for key in keys:
        if key not in metrics:
            continue
        try:
            return int(metrics.get(key) or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _latest_graph_sync_run_snapshot(session: Session | None, *, course_id: str) -> dict[str, Any] | None:
    if session is None:
        return None
    sync_run = session.exec(
        select(KnowledgeGraphSyncRun)
        .where(KnowledgeGraphSyncRun.course_id == course_id)
        .order_by(KnowledgeGraphSyncRun.updated_at.desc(), KnowledgeGraphSyncRun.id.desc())
    ).first()
    if sync_run is None:
        return None
    try:
        metrics = json.loads(sync_run.metrics_json or "{}")
    except json.JSONDecodeError:
        metrics = {}
    if not isinstance(metrics, dict):
        metrics = {}
    return {
        "build_session_id": sync_run.build_session_id,
        "status": str(sync_run.status or "").strip() or "idle",
        "doc_version_no": int(sync_run.doc_version_no or 0),
        "graph_revision_no": int(sync_run.graph_revision_no or 0),
        "metrics": metrics,
        "error_message": sync_run.error_message,
        "started_at": sync_run.started_at,
        "finished_at": sync_run.finished_at,
    }


def _build_graph_metrics_from_sync_run(snapshot: dict[str, Any] | None) -> KnowledgeGraphBuildMetricsResponse:
    if snapshot is None:
        return KnowledgeGraphBuildMetricsResponse()
    metrics = snapshot.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}
    return KnowledgeGraphBuildMetricsResponse(
        doc_sync_section_count=_int_metric(metrics, "doc_sync_section_count", "section_count"),
        doc_sync_unit_changes=_int_metric(metrics, "doc_sync_unit_changes", "unit_change_count"),
        doc_sync_edge_changes=_int_metric(metrics, "doc_sync_edge_changes", "edge_change_count"),
        doc_sync_rule_fallback_attempt_count=_int_metric(
            metrics,
            "doc_sync_rule_fallback_attempt_count",
            "rule_fallback_attempt_count",
        ),
        doc_sync_rule_fallback_success_count=_int_metric(
            metrics,
            "doc_sync_rule_fallback_success_count",
            "rule_fallback_success_count",
        ),
        elapsed_ms=_int_metric(metrics, "elapsed_ms"),
        revision_no=int(snapshot.get("graph_revision_no") or 0),
        last_synced_doc_version_no=int(snapshot.get("doc_version_no") or 0),
        knowledge_doc_chapter_count=_int_metric(metrics, "knowledge_doc_chapter_count", "chapter_count"),
        source_ref_count=_int_metric(metrics, "source_ref_count"),
        backbone_unit_count=_int_metric(metrics, "backbone_unit_count"),
        backbone_edge_count=_int_metric(metrics, "backbone_edge_count"),
        stable_anchor_count=_int_metric(metrics, "stable_anchor_count"),
        deprecated_unit_count=_int_metric(metrics, "deprecated_unit_count"),
        deprecated_edge_count=_int_metric(metrics, "deprecated_edge_count"),
        prefetch_section_count=_int_metric(metrics, "prefetch_section_count"),
        prefetch_reused_section_count=_int_metric(metrics, "prefetch_reused_section_count"),
        prefetch_catchup_section_count=_int_metric(metrics, "prefetch_catchup_section_count"),
        prefetch_stale_section_count=_int_metric(metrics, "prefetch_stale_section_count"),
        prefetch_failed_section_count=_int_metric(metrics, "prefetch_failed_section_count"),
    )


def _build_graph_lane_runtime_from_sync_run(
    snapshot: dict[str, Any] | None,
) -> KnowledgeBuildLaneRuntimeResponse | None:
    if snapshot is None:
        return None
    status = str(snapshot.get("status") or "").strip() or "idle"
    stage = status if status in {"completed", "failed", "cancelled", "partial_failed"} else "graph_docs_sync"
    metrics = _build_graph_metrics_from_sync_run(snapshot)
    return KnowledgeBuildLaneRuntimeResponse(
        lane="graph",
        build_group_id=str(snapshot.get("build_session_id") or "").strip() or None,
        status=status,
        stage=stage,
        started_at=snapshot.get("started_at"),
        finished_at=snapshot.get("finished_at"),
        requested_at=snapshot.get("started_at"),
        error_message=sanitize_knowledge_build_error_message(
            snapshot.get("error_message"),
            build_kind="graph",
        ),
        progress_pct=100 if status in {"completed", "partial_failed"} else 0,
        current_stage_description="知识图谱同步已完成" if status == "completed" else None,
        metrics=metrics.model_dump(),
    )


def _resolve_runtime_build_status(
    *,
    course_id: str,
    session: Session | None = None,
    course_scope: CourseStorageScope | None = None,
) -> KnowledgeBuildStatusResponse | None:
    runtime = read_knowledge_build_runtime(course_id, course_scope=course_scope)
    effective = runtime.docgen_runtime if runtime is not None else None
    if effective is None:
        build_lock = read_knowledge_build_lock(course_id, session=session, course_scope=course_scope)
    else:
        build_lock = None
    if effective is None and build_lock is not None:
        effective = update_knowledge_build_lane_status(
            course_id,
            lane="docgen",
            course_scope=course_scope,
            requested_at=build_lock.requested_at,
            build_group_id=build_lock.build_group_id,
            status="running",
            stage="build_accepted",
            source_file_ids=build_lock.source_file_ids,
            prompt=build_lock.prompt,
        )
        runtime = read_knowledge_build_runtime(course_id, course_scope=course_scope)
        effective = runtime.docgen_runtime if runtime is not None else None
    if effective is None:
        return None
    return KnowledgeBuildStatusResponse(
        status=effective.status,
        requested_at=effective.requested_at,
        stage=effective.stage,
        error_message=sanitize_knowledge_build_error_message(
            effective.error_message,
            build_kind=effective.build_kind,
        ),
        draft_available=bool(effective.draft_available),
        progress_pct=effective.progress_pct,
        planner_session_id=effective.planner_session_id,
        confirmed_plan_id=effective.confirmed_plan_id,
        digest_mode=effective.digest_mode,
        mode_reason=effective.mode_reason,
        current_stage_description=effective.current_stage_description,
    )


def _build_lane_runtime_response(
    lane: str,
    runtime_status,
) -> KnowledgeBuildLaneRuntimeResponse | None:
    if runtime_status is None:
        return None
    return KnowledgeBuildLaneRuntimeResponse(
        lane=lane,
        build_group_id=runtime_status.build_group_id,
        status=runtime_status.status,
        stage=runtime_status.stage,
        started_at=runtime_status.started_at,
        finished_at=runtime_status.finished_at,
        requested_at=runtime_status.requested_at,
        error_message=sanitize_knowledge_build_error_message(
            runtime_status.error_message,
            build_kind=runtime_status.build_kind,
        ),
        progress_pct=runtime_status.progress_pct,
        current_stage_description=runtime_status.current_stage_description,
        metrics=dict(runtime_status.metrics or {}),
    )


def get_knowledge_build_runtime_result(
    session: Session | None = None,
    *,
    course_id: str,
    course_scope: CourseStorageScope | None = None,
) -> KnowledgeBuildRuntimeResponse:
    course_scope = course_scope or resolve_course_storage_scope(course_id, session=session)
    draft_markdown = normalize_mermaid_blocks(
        run_store_sync(
            get_content_store().read_text,
            course_scope.knowledge_build_prefix() + "merged_knowledge_base.md",
            default="",
        ) or ""
    )
    manifest = read_knowledge_manifest(course_id, course_scope=course_scope)
    runtime = read_knowledge_build_runtime(course_id, course_scope=course_scope)
    graph_expected = bool(get_settings().knowledge_graph.sync_after_docgen)
    aggregate_runtime = build_aggregate_knowledge_build_status(
        runtime,
        graph_expected=graph_expected,
    )
    docgen_runtime = runtime.docgen_runtime if runtime is not None else None
    graph_runtime = runtime.graph_runtime if runtime is not None else None
    docs_ready = manifest is not None
    graph_status = (graph_runtime.status if graph_runtime is not None else "").strip()
    graph_sync_snapshot = None
    graph_lane = _build_lane_runtime_response("graph", graph_runtime)
    graph_metrics = _build_graph_metrics(build_status=graph_runtime)
    if not graph_status:
        graph_sync_snapshot = _latest_graph_sync_run_snapshot(session, course_id=course_id)
        if graph_sync_snapshot is not None:
            graph_status = str(graph_sync_snapshot.get("status") or "").strip() or "idle"
            graph_lane = _build_graph_lane_runtime_from_sync_run(graph_sync_snapshot)
            graph_metrics = _build_graph_metrics_from_sync_run(graph_sync_snapshot)
        else:
            graph_status = "skipped" if docs_ready else "idle"
    graph_training_ready_statuses = {"completed", "partial_failed", "skipped"}
    graph_unhealthy = graph_status in {"failed", "cancelled"}
    training_unlocked = bool(docs_ready and graph_status in graph_training_ready_statuses)
    return KnowledgeBuildRuntimeResponse(
        build_group_id=(
            aggregate_runtime.build_group_id
            if aggregate_runtime is not None
            else (
                runtime.build_group_id
                if runtime is not None
                else (
                    str(graph_sync_snapshot.get("build_session_id") or "").strip() or None
                    if graph_sync_snapshot is not None
                    else None
                )
            )
        ),
        docs_ready=docs_ready,
        graph_status=graph_status,
        graph_unhealthy=graph_unhealthy,
        training_unlocked=training_unlocked,
        aggregate=_build_lane_runtime_response("aggregate", aggregate_runtime),
        docgen=_build_lane_runtime_response("docgen", docgen_runtime),
        graph=graph_lane,
        docgen_preview=_build_runtime_preview(
            build_status=docgen_runtime,
            draft_markdown=draft_markdown,
            manifest=manifest,
        ),
        docgen_metrics=_build_runtime_metrics(build_status=docgen_runtime),
        graph_metrics=graph_metrics,
    )


def _build_confirmed_plan_payload(
    plan: ConfirmedBuildPlan,
    *,
    fallback_course_name: str | None = None,
) -> dict[str, Any]:
    payload = dict(plan.plan_json or {})
    course_name = str(
        payload.get("course_name")
        or fallback_course_name
        or getattr(plan, "course_name", "")
        or ""
    ).strip()
    payload["course_name"] = course_name
    payload.setdefault("user_prompt", plan.user_prompt)
    payload.setdefault("digest_mode", plan.digest_mode)
    payload.setdefault("chapters", list(plan.chapters))
    payload.setdefault("build_constraints", dict(plan.build_constraints))
    payload.setdefault("plan", plan.plan)
    payload["selected_file_ids"] = list(plan.selected_file_ids)
    payload["planner_session_id"] = plan.planner_session_id
    payload["confirmed_plan_id"] = plan.id
    payload["confirmed_plan_version_no"] = int(plan.version_no or 1)
    payload["model_override"] = normalize_runtime_model_override(payload.get("model_override")) or ""
    return normalize_digest_confirmed_plan_payload(payload)


def _confirmed_plan_model_override(plan_payload: dict[str, Any] | None) -> str | None:
    return normalize_runtime_model_override((plan_payload or {}).get("model_override"))


def _load_confirmed_plan_payload(
    *,
    course_id: str,
    user_id: str,
    confirmed_plan_id: str,
    fallback_course_name: str | None = None,
) -> tuple[ConfirmedBuildPlan, dict[str, Any]]:
    with managed_session() as session:
        plan = get_confirmed_build_plan(
            session,
            course_id=course_id,
            user_id=user_id,
            plan_id=confirmed_plan_id,
        )
    return plan, _build_confirmed_plan_payload(plan, fallback_course_name=fallback_course_name)


def trigger_docgen_build(
    session: Session,
    *,
    course: Course,
    user_id: str,
    file_ids: list[str] | None,
    prompt: str | None,
    embedding_resolution: str | None,
    confirmed_plan_id: str | None,
) -> tuple[DocGenBuildData, list[str], str]:
    """处理知识文档构建请求的同步前置阶段。

    这里还没有启动 LangGraph。它只负责确认 plan、选择可用文件、处理向量
    precheck、写 build lock / status，并把后台任务需要的 file_ids 和响应
    数据交给 API 层。
    """

    conflict = inspect_course_build_precheck(session, course=course)
    vector_status = resolve_course_build_vector_status(
        session,
        course=course,
        embedding_resolution=embedding_resolution,
        prechecked_conflict=conflict,
    )
    force_full_rebuild = bool(
        conflict is not None
        and conflict.requires_full_rebuild
        and vector_status.mode != "disabled"
    )
    if force_full_rebuild:
        clear_chunk_vector_metadata(session, course_id=course.id)
    planner_session_id = None
    digest_mode = None
    planner_plan = None
    model_override = None
    chapter_progress: list[dict[str, object]] = []
    recent_events: list[dict[str, object]] = []
    cleaned_prompt = _clean_prompt(prompt)
    if not confirmed_plan_id:
        raise ConfirmedBuildPlanRequiredError("docs")

    plan = get_confirmed_build_plan(
        session,
        course_id=course.id,
        user_id=user_id,
        plan_id=confirmed_plan_id,
    )
    if plan.status == "building":
        raise CourseBuildLockConflictError(course.id)
    planner_session_id = plan.planner_session_id
    digest_mode = plan.digest_mode
    planner_plan = str((plan.plan_json or {}).get("plan") or plan.plan or "")
    model_override = _confirmed_plan_model_override(plan.plan_json)
    chapter_progress = _build_initial_chapter_progress(plan)
    recent_events = [
        {
            "stage": "build_accepted",
            "chapter_index": None,
            "title": None,
            "summary": f"方案已确认，共 {len(chapter_progress)} 章，构建请求已受理。",
            "created_at": utcnow(),
        }
    ]
    accepted_files, ready_file_count = _select_ready_docgen_files_by_ids(
        session,
        course_id=course.id,
        file_ids=list(plan.selected_file_ids),
        allow_empty=True,
    )
    plan_prompt = _clean_prompt(plan.user_prompt) or _clean_prompt(planner_plan)
    if file_ids:
        logger.warning(
            "knowledge_build_file_selection_ignored_for_confirmed_plan",
            course_id=course.id,
            confirmed_plan_id=confirmed_plan_id,
            requested_file_id_count=len(file_ids),
        )
    if cleaned_prompt and plan_prompt and cleaned_prompt != plan_prompt:
        logger.warning(
            "knowledge_build_prompt_ignored_for_confirmed_plan",
            course_id=course.id,
            confirmed_plan_id=confirmed_plan_id,
        )
    cleaned_prompt = plan_prompt or cleaned_prompt
    accepted_file_ids = _resolve_file_ids(accepted_files)
    search_only_mode = not accepted_file_ids
    if search_only_mode:
        recent_events.append(
            {
                "stage": "search_only_mode",
                "chapter_index": None,
                "title": None,
                "summary": "当前没有已解析资料，本轮将以外部检索为主生成知识文档。",
                "created_at": utcnow(),
            }
        )
    requested_at = utcnow()
    build_group_id = _new_build_session_id()
    build_lock = KnowledgeBuildLock(
        requested_at=requested_at,
        build_group_id=build_group_id,
        source_file_ids=accepted_file_ids,
        prompt=cleaned_prompt,
    )
    course_scope = build_course_storage_scope(user_id=course.user_id, course_id=course.id)
    if not acquire_knowledge_build_lock(course.id, build_lock, course_scope=course_scope):
        raise CourseBuildLockConflictError(course.id)
    _clear_docgen_staging_safely(course.id, course_scope=course_scope)
    update_knowledge_build_lane_status(
        course.id,
        lane="docgen",
        course_scope=course_scope,
        requested_at=requested_at,
        build_group_id=build_group_id,
        status="accepted",
        stage="build_accepted",
        error_message=None,
        draft_available=False,
        source_file_ids=accepted_file_ids,
        prompt=cleaned_prompt,
        staged_chapter_count=0,
        published_doc_count=0,
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        digest_mode=digest_mode,
        model_override=model_override,
        plan=planner_plan,
        chapter_progress=chapter_progress,
        recent_events=recent_events,
        current_stage_description=(
            "方案已确认，当前没有本地资料，将优先执行联网研究。"
            if search_only_mode
            else ("方案已确认，正在排队启动构建。" if confirmed_plan_id else None)
        ),
    )
    logger.info(
        "knowledge_build_requested",
        course_id=course.id,
        requested_at=requested_at.isoformat(),
        file_count=len(accepted_file_ids),
        force_full_rebuild=force_full_rebuild,
        vector_mode=vector_status.mode,
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        search_only_mode=search_only_mode,
        build_group_id=build_group_id,
        model_override=model_override,
    )
    build_data = DocGenBuildData(
        accepted_file_ids=accepted_file_ids,
        ready_file_count=ready_file_count,
        prompt=cleaned_prompt,
        requested_at=requested_at,
        vector_status=vector_status,
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        digest_mode=digest_mode,
        model_override=model_override,
    )
    return build_data, accepted_file_ids, build_group_id


async def run_docgen_background(
    *,
    course_id: str,
    course_name: str | None = None,
    file_ids: list[str],
    prompt: str | None,
    requested_at: datetime,
    build_group_id: str,
    planner_session_id: str | None = None,
    confirmed_plan_id: str | None = None,
    model_override: str | None = None,
    user_id: str | None = None,
    background_task_registry: Any | None = None,
) -> None:
    """后台执行 DocGen 构建生命周期。

    负责把 API 接受的构建请求转成一次真实 workflow run：加载 confirmed
    plan、运行 `run_docgen_workflow`、持久化知识文档、
    更新状态并释放构建锁。自动图谱固化已经是 DocGen 图内的最终节点；异常处理也集中在这里，避免 API 层持有
    长任务细节。
    """

    from app.workflows.digest import run_docgen_workflow
    from app.shared.infra.knowledge.build_store import release_knowledge_build_lock
    from app.workflows.digest.kg_doc_sync.lib.prefetch import cancel_docgen_kg_prefetch
    build_session_id = _new_build_session_id()
    confirmed_plan_payload = None
    resolved_digest_mode = None
    resolved_model_override = normalize_runtime_model_override(model_override)
    sync_graph_after_docgen = bool(get_settings().knowledge_graph.sync_after_docgen)
    docgen_published = False
    course_scope: CourseStorageScope | None = None
    lifecycle_started_at = perf_counter()
    lifecycle_outputs: dict[str, object] = {
        "status": "running",
        "build_session_id": build_session_id,
        "build_group_id": build_group_id,
    }
    lifecycle_trace_cm = langsmith_trace(
        name="知识构建：后台构建生命周期",
        run_type="chain",
        inputs=sanitize_langsmith_input(
            {
                "course_id": course_id,
                "course_name": course_name or "",
                "file_ids_count": len(file_ids),
                "prompt_chars": len(prompt or ""),
                "requested_at": requested_at.isoformat(),
                "build_group_id": build_group_id,
                "build_session_id": build_session_id,
                "planner_session_id": planner_session_id or "",
                "confirmed_plan_id": confirmed_plan_id or "",
                "model_override": resolved_model_override,
                "sync_graph_after_docgen": sync_graph_after_docgen,
            },
            field_name="docgen_lifecycle_inputs",
        ),
        course_id=course_id,
        build_session_id=build_session_id,
        workflow="digest.docgen.lifecycle",
        lane="docgen",
        extra_metadata={
            "workflow_trace_kind": "background_lifecycle_root",
            "build_group_id": build_group_id,
            "planner_session_id": planner_session_id or "",
            "confirmed_plan_id": confirmed_plan_id or "",
        },
        extra_tags=["docgen:lifecycle"],
    )
    try:
        lifecycle_trace_run = lifecycle_trace_cm.__enter__()
        lifecycle_trace_active = True
    except Exception as exc:  # pragma: no cover - observability best effort
        logger.warning("docgen_lifecycle_trace_start_failed", course_id=course_id, error=str(exc))
        lifecycle_trace_cm = nullcontext(None)
        lifecycle_trace_run = None
        lifecycle_trace_active = False
    lifecycle_trace_closed = False

    def _finish_lifecycle_trace() -> None:
        nonlocal lifecycle_trace_closed
        if lifecycle_trace_closed:
            return
        lifecycle_trace_closed = True
        exc_info = sys.exc_info()
        lifecycle_outputs.setdefault("elapsed_ms", int((perf_counter() - lifecycle_started_at) * 1000))
        try:
            if lifecycle_trace_run is not None:
                lifecycle_trace_run.end(
                    outputs=sanitize_langsmith_output(
                        lifecycle_outputs,
                        field_name="docgen_lifecycle_outputs",
                    )
                )
        except Exception as exc:  # pragma: no cover - observability best effort
            logger.warning("docgen_lifecycle_trace_end_failed", course_id=course_id, error=str(exc))
        try:
            if lifecycle_trace_active:
                lifecycle_trace_cm.__exit__(*exc_info)
        except Exception as exc:  # pragma: no cover - observability best effort
            logger.warning(
                "docgen_lifecycle_trace_context_close_failed",
                course_id=course_id,
                error=str(exc),
            )

    logger.info(
        "knowledge_build_background_started",
        course_id=course_id,
        requested_at=requested_at.isoformat(),
        file_count=len(file_ids),
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        model_override=resolved_model_override,
        user_id=user_id,
        build_group_id=build_group_id,
    )
    if not confirmed_plan_id or not user_id:
        _write_docgen_status(
            course_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            status="failed",
            stage="failed",
            build_session_id=build_session_id,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=resolved_digest_mode,
            model_override=resolved_model_override,
            error_message="confirmed_plan_required",
            draft_available=False,
        )
        logger.error("knowledge_build_failed_missing_confirmed_plan", course_id=course_id)
        lifecycle_outputs = {
            "status": "failed",
            "stage": "confirmed_plan_required",
            "build_session_id": build_session_id,
            "build_group_id": build_group_id,
        }
        release_knowledge_build_lock(course_id)
        _finish_lifecycle_trace()
        return

    course_scope = build_course_storage_scope(user_id=user_id, course_id=course_id)
    try:
        plan, confirmed_plan_payload = _load_confirmed_plan_payload(
            course_id=course_id,
            user_id=user_id,
            confirmed_plan_id=confirmed_plan_id,
            fallback_course_name=course_name,
        )
        planner_session_id = planner_session_id or plan.planner_session_id
        resolved_digest_mode = plan.digest_mode
        resolved_model_override = _confirmed_plan_model_override(confirmed_plan_payload) or resolved_model_override
        _mark_confirmed_plan_status(
            course_id=course_id,
            user_id=user_id,
            confirmed_plan_id=confirmed_plan_id,
            status="building",
        )
        _clear_docgen_staging_safely(course_id, course_scope=course_scope)
        _write_docgen_status(
            course_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            course_scope=course_scope,
            status="running",
            stage="prepare_shared",
            build_session_id=build_session_id,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=resolved_digest_mode,
            model_override=resolved_model_override,
            error_message=None,
            draft_available=False,
            source_file_ids=file_ids,
            prompt=prompt,
        )
        if sync_graph_after_docgen:
            _write_graph_status(
                course_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                course_scope=course_scope,
                status="accepted",
                stage="queued_after_docgen",
                source_file_ids=file_ids,
                prompt=prompt,
                model_override=resolved_model_override,
                current_stage_description="知识文档发布后将自动开始图谱同步。",
            )
        else:
            _write_graph_status(
                course_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                course_scope=course_scope,
                status="skipped",
                stage="disabled",
                source_file_ids=file_ids,
                prompt=prompt,
                model_override=resolved_model_override,
                current_stage_description="已关闭文档构建后自动图谱同步。",
            )
        result = await run_docgen_workflow(
            course_id=course_id,
            course_name=course_name,
            user_id=user_id,
            file_ids=file_ids,
            user_prompt=prompt,
            requested_at=requested_at,
            build_group_id=build_group_id,
            build_session_id=build_session_id,
            confirmed_plan=confirmed_plan_payload,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=resolved_digest_mode,
            model_override=resolved_model_override,
        )
        if result.failed:
            cancel_docgen_kg_prefetch(course_id=course_id, build_session_id=build_session_id)
            if sync_graph_after_docgen:
                _write_graph_status(
                    course_id,
                    requested_at=requested_at,
                    build_group_id=build_group_id,
                    course_scope=course_scope,
                    status="skipped",
                    stage="blocked_by_docgen_failure",
                    current_stage_description="知识文档构建失败，未继续图谱同步。",
            )
            _clear_docgen_staging_safely(course_id, course_scope=course_scope)
            _write_docgen_status(
                course_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                course_scope=course_scope,
                status="failed",
                stage="failed",
                build_session_id=build_session_id,
                planner_session_id=planner_session_id,
                confirmed_plan_id=confirmed_plan_id,
                digest_mode=resolved_digest_mode,
                error_message=result.error.detail,
                draft_available=False,
            )
            _mark_confirmed_plan_status(
                course_id=course_id,
                user_id=user_id,
                confirmed_plan_id=confirmed_plan_id,
                status="failed",
            )
            logger.error("knowledge_build_failed", course_id=course_id, error=result.error.detail)
            lifecycle_outputs = {
                "status": "failed",
                "stage": "workflow_failed",
                "build_session_id": build_session_id,
                "build_group_id": build_group_id,
                "error": result.error.detail,
            }
            return
        final_docgen_state = result.require_value()
        _write_docgen_status(
            course_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            course_scope=course_scope,
            status="completed",
            stage="completed",
            build_session_id=build_session_id,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=resolved_digest_mode,
            error_message=None,
            draft_available=False,
            metrics=dict(final_docgen_state.get("kg_prefetch_metrics") or {}),
            current_stage_description="知识文档已发布完成。",
        )
        docgen_published = True
        if sync_graph_after_docgen:
            logger.info(
                "knowledge_graph_auto_build_completed_in_docgen",
                course_id=course_id,
                build_group_id=build_group_id,
                graph_sync_status=final_docgen_state.get("graph_sync_status"),
            )
        else:
            _write_graph_status(
                course_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                course_scope=course_scope,
                status="skipped",
                stage="disabled",
                source_file_ids=file_ids,
                prompt=prompt,
                current_stage_description="已关闭文档构建后自动图谱同步，可在知识图谱面板手动构建。",
            )
        _mark_confirmed_plan_status(
            course_id=course_id,
            user_id=user_id,
            confirmed_plan_id=confirmed_plan_id,
            status="completed",
        )
        lifecycle_outputs = {
            "status": "completed",
            "stage": "completed",
            "build_session_id": build_session_id,
            "build_group_id": build_group_id,
            "docgen_published": docgen_published,
            "graph_sync_status": final_docgen_state.get("graph_sync_status"),
        }
    except asyncio.CancelledError:
        cancel_docgen_kg_prefetch(course_id=course_id, build_session_id=build_session_id)
        if sync_graph_after_docgen and not docgen_published:
            _write_graph_status(
                course_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                course_scope=course_scope,
                status="cancelled",
                stage="cancelled",
                error_message="build_cancelled",
                current_stage_description="图谱构建已取消。",
        )
        if not docgen_published:
            _clear_docgen_staging_safely(course_id, course_scope=course_scope)
            _write_docgen_status(
                course_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                course_scope=course_scope,
                status="cancelled",
                stage="cancelled",
                build_session_id=build_session_id,
                planner_session_id=planner_session_id,
                confirmed_plan_id=confirmed_plan_id,
                digest_mode=resolved_digest_mode,
                error_message="build_cancelled",
                draft_available=False,
            )
        _mark_confirmed_plan_status(
            course_id=course_id,
            user_id=user_id,
            confirmed_plan_id=confirmed_plan_id,
            status="completed" if docgen_published else "cancelled",
        )
        lifecycle_outputs = {
            "status": "cancelled",
            "stage": "cancelled",
            "build_session_id": build_session_id,
            "build_group_id": build_group_id,
            "docgen_published": docgen_published,
        }
        raise
    except Exception as exc:
        cancel_docgen_kg_prefetch(course_id=course_id, build_session_id=build_session_id)
        if sync_graph_after_docgen and not docgen_published:
            _write_graph_status(
                course_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                course_scope=course_scope,
                status="skipped",
                stage="blocked_by_docgen_failure",
                current_stage_description="知识文档构建异常失败，未完成图谱同步。",
        )
        if not docgen_published:
            _clear_docgen_staging_safely(course_id, course_scope=course_scope)
            _write_docgen_status(
                course_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                course_scope=course_scope,
                status="failed",
                stage="failed",
                build_session_id=build_session_id,
                planner_session_id=planner_session_id,
                confirmed_plan_id=confirmed_plan_id,
                digest_mode=resolved_digest_mode,
                error_message="build_crashed",
                draft_available=False,
            )
        _mark_confirmed_plan_status(
            course_id=course_id,
            user_id=user_id,
            confirmed_plan_id=confirmed_plan_id,
            status="completed" if docgen_published else "failed",
        )
        logger.exception("knowledge_build_failed", course_id=course_id)
        lifecycle_outputs = {
            "status": "failed",
            "stage": "crashed",
            "build_session_id": build_session_id,
            "build_group_id": build_group_id,
            "docgen_published": docgen_published,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
        return
    finally:
        _finish_lifecycle_trace()
        if course_scope is not None:
            release_knowledge_build_lock(course_id, course_scope=course_scope)


def get_docgen_result(
    session: Session | None = None,
    *,
    course_id: str,
    course_scope: CourseStorageScope | None = None,
) -> DocGenGetResponse:
    """组装知识文档页面轮询所需的当前状态。

    读取已发布 Markdown、构建中草稿、manifest、build status、preview 和
    LLM 统计；该函数不触发构建，只服务 `/knowledge/docs` 轮询查询。
    """

    cs = get_content_store()
    course_scope = course_scope or resolve_course_storage_scope(course_id, session=session)
    draft_key = course_scope.knowledge_build_prefix() + "merged_knowledge_base.md"
    manifest = read_knowledge_manifest(course_id, course_scope=course_scope)
    runtime = read_knowledge_build_runtime(course_id, course_scope=course_scope)
    docgen_build_status = runtime.docgen_runtime if runtime is not None else None
    try:
        markdown, published_updated_at = _load_current_published_markdown(
            session,
            course_id=course_id,
            course_scope=course_scope,
            manifest=manifest,
        )
    except Exception as exc:
        logger.warning(
            "docgen_result_published_markdown_degraded",
            course_id=course_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        markdown, published_updated_at = "", None
    else:
        try:
            markdown = apply_interactive_overlays_to_markdown(
                markdown,
                overlays=load_current_interactive_overlays(
                    course_scope,
                    version_no=(manifest.version_no if manifest is not None else 0),
                ),
            )
        except Exception as exc:
            logger.warning(
                "docgen_result_interactive_overlays_degraded",
                course_id=course_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
    draft_markdown = sanitize_public_markdown(
        normalize_mermaid_blocks(
            normalize_markdown_rendering(run_store_sync(cs.read_text, draft_key, default="") or "")
        )
    )
    updated_at = published_updated_at or (manifest.updated_at if manifest is not None else None)
    draft_updated_at = (
        docgen_build_status.draft_updated_at
        if docgen_build_status is not None and docgen_build_status.draft_updated_at is not None
        else None
    )
    source_file_ids: list[str] = list(manifest.source_file_ids) if manifest is not None else []
    try:
        build_response = _resolve_runtime_build_status(
            course_id=course_id,
            session=session,
            course_scope=course_scope,
        )
    except Exception as exc:
        logger.warning(
            "docgen_result_build_status_degraded",
            course_id=course_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        build_response = None
    if build_response is not None:
        build_response.draft_available = bool(build_response.draft_available or draft_markdown.strip())
    build_preview = _build_runtime_preview(
        build_status=docgen_build_status,
        draft_markdown=draft_markdown,
        manifest=manifest,
    )
    build_metrics = _build_runtime_metrics(build_status=docgen_build_status)
    try:
        with _session_context(session) as db_session:
            vector_status = get_course_vector_status_by_id(db_session, course_id)
    except Exception as exc:
        logger.warning(
            "docgen_result_vector_status_degraded",
            course_id=course_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        vector_status = CourseVectorStatusResponse()

    return DocGenGetResponse(
        exists=bool(markdown.strip()),
        markdown=markdown,
        updated_at=updated_at,
        source_file_ids=source_file_ids,
        prompt=(manifest.prompt if manifest is not None else None),
        draft_markdown=draft_markdown,
        draft_updated_at=draft_updated_at,
        build=build_response,
        build_preview=build_preview,
        build_metrics=build_metrics,
        vector_status=vector_status,
        planner_session_id=(build_response.planner_session_id if build_response is not None else None),
        confirmed_plan_id=(build_response.confirmed_plan_id if build_response is not None else None),
        digest_mode=(build_response.digest_mode if build_response is not None else None),
    )


__all__ = ["get_docgen_result", "get_knowledge_build_runtime_result", "run_docgen_background", "trigger_docgen_build"]
