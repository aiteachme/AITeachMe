"""DocGen build lifecycle around the graph runtime.

This module owns the API-facing lifecycle around one DocGen request:
file selection, confirmed-plan loading, build locking, background
execution, runtime polling, and result assembly.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import nullcontext
from datetime import datetime
from typing import Any

import structlog
from sqlmodel import Session

from app.models.build_planner import ConfirmedBuildPlan
from app.models.raw_file import RawFile
from app.models.subject import Subject
from app.repositories.files_repo import list_all_raw_files_by_subject, list_raw_files_by_ids
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
    SubjectVectorStatusResponse,
)
from app.shared.infra.database import managed_session
from app.shared.infra.exceptions import (
    ConfirmedBuildPlanRequiredError,
    NoReadyFilesForDocGenError,
    SubjectBuildLockConflictError,
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
from app.shared.infra.llm_support.common import capture_llm_runtime_snapshot
from app.shared.infra.settings import get_settings
from app.shared.infra.storage import (
    SubjectStorageScope,
    build_subject_storage_scope,
    get_content_store,
    resolve_subject_storage_scope,
    run_store_sync,
)
from app.shared.infra.subject import (
    get_subject_vector_status_by_id,
    inspect_subject_build_precheck,
    resolve_subject_build_vector_status,
)
from app.shared.infra.tools.builtin.markdown_processing import normalize_mermaid_blocks
from app.utils.presenters import require_id
from app.utils.time import utcnow
from app.workflows.digest.common.contracts import normalize_digest_confirmed_plan_payload
from app.workflows.digest.common.file_status import is_markdown_ready_for_digest
from app.workflows.digest.common.metrics import build_token_summary
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
    subject_id: str,
    file_ids: list[str],
    allow_empty: bool = False,
) -> tuple[list[RawFile], int]:
    all_files = list_all_raw_files_by_subject(session, subject_id)
    ready_files = [item for item in all_files if item.id and is_markdown_ready_for_digest(item)]
    ready_ids = {require_id(item.id, "RawFile.id") for item in ready_files}
    requested = {
        require_id(item.id, "RawFile.id"): item
        for item in list_raw_files_by_ids(session, subject_id, file_ids)
        if item.id
    }
    accepted = [requested[file_id] for file_id in file_ids if file_id in requested and file_id in ready_ids]
    if not accepted and not allow_empty:
        raise NoReadyFilesForDocGenError(subject_id)
    return accepted, len(ready_files)


def _resolve_file_ids(raw_files: list[RawFile]) -> list[str]:
    return [require_id(item.id, "RawFile.id") for item in raw_files]


def _new_build_session_id() -> str:
    return uuid.uuid4().hex


def _session_context(session: Session | None):
    return nullcontext(session) if session is not None else managed_session()


def _clear_docgen_staging_safely(
    subject_id: str,
    *,
    subject_scope: SubjectStorageScope | None = None,
) -> None:
    try:
        clear_docgen_staging(subject_id, subject_scope=subject_scope)
    except Exception:
        logger.exception("knowledge_build_cleanup_failed", subject_id=subject_id)


def _write_docgen_status(
    subject_id: str,
    *,
    requested_at: datetime,
    status: str,
    stage: str,
    subject_scope: SubjectStorageScope | None = None,
    **extra: object,
) -> None:
    update_knowledge_build_lane_status(
        subject_id,
        lane="docgen",
        subject_scope=subject_scope,
        requested_at=requested_at,
        status=status,
        stage=stage,
        **extra,
    )


def _write_graph_status(
    subject_id: str,
    *,
    requested_at: datetime,
    status: str,
    stage: str,
    subject_scope: SubjectStorageScope | None = None,
    **extra: object,
) -> None:
    update_knowledge_build_lane_status(
        subject_id,
        lane="graph",
        subject_scope=subject_scope,
        requested_at=requested_at,
        status=status,
        stage=stage,
        **extra,
    )


def _mark_confirmed_plan_status(
    *,
    subject_id: str,
    user_id: str,
    confirmed_plan_id: str,
    status: str,
) -> None:
    with managed_session() as session:
        mark_confirmed_build_plan_status(
            session,
            subject_id=subject_id,
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


def _load_current_published_markdown(
    session: Session | None,
    *,
    subject_id: str,
    subject_scope: SubjectStorageScope,
    manifest,
) -> tuple[str, datetime | None]:
    cs = get_content_store()
    stored_markdown = normalize_mermaid_blocks(
        run_store_sync(
            cs.read_text,
            subject_scope.knowledge_doc_key("merged_knowledge_base.md"),
            default="",
        )
        or ""
    ).strip()
    if stored_markdown:
        return stored_markdown, manifest.updated_at if manifest is not None else None

    with _session_context(session) as db_session:
        docs = get_current_published_docs(db_session, subject_id)
    parts: list[str] = []
    updated_at: datetime | None = None
    for doc in docs:
        markdown = normalize_mermaid_blocks(str(doc.markdown_content or doc.content_markdown or "").strip())
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
    chapter_plan = list(plan.chapter_plan_json or [])
    progress: list[dict[str, object]] = []
    for index, chapter in enumerate(chapter_plan, start=1):
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
        plan_summary=(build_status.plan_summary if build_status is not None else None),
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


def _resolve_runtime_build_status(
    *,
    subject_id: str,
    session: Session | None = None,
    subject_scope: SubjectStorageScope | None = None,
) -> KnowledgeBuildStatusResponse | None:
    runtime = read_knowledge_build_runtime(subject_id, subject_scope=subject_scope)
    effective = runtime.docgen_runtime if runtime is not None else None
    if effective is None:
        build_lock = read_knowledge_build_lock(subject_id, session=session)
    else:
        build_lock = None
    if effective is None and build_lock is not None:
        effective = update_knowledge_build_lane_status(
            subject_id,
            lane="docgen",
            subject_scope=subject_scope,
            requested_at=build_lock.requested_at,
            build_group_id=build_lock.build_group_id,
            status="running",
            stage="build_accepted",
            source_file_ids=build_lock.source_file_ids,
            prompt=build_lock.prompt,
        )
        runtime = read_knowledge_build_runtime(subject_id, subject_scope=subject_scope)
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
    subject_id: str,
    subject_scope: SubjectStorageScope | None = None,
) -> KnowledgeBuildRuntimeResponse:
    subject_scope = subject_scope or resolve_subject_storage_scope(subject_id, session=session)
    draft_markdown = normalize_mermaid_blocks(
        run_store_sync(
            get_content_store().read_text,
            subject_scope.knowledge_build_prefix() + "merged_knowledge_base.md",
            default="",
        ) or ""
    )
    manifest = read_knowledge_manifest(subject_id, subject_scope=subject_scope)
    runtime = read_knowledge_build_runtime(subject_id, subject_scope=subject_scope)
    aggregate_runtime = build_aggregate_knowledge_build_status(runtime)
    docgen_runtime = runtime.docgen_runtime if runtime is not None else None
    graph_runtime = runtime.graph_runtime if runtime is not None else None
    return KnowledgeBuildRuntimeResponse(
        build_group_id=(
            aggregate_runtime.build_group_id
            if aggregate_runtime is not None
            else (runtime.build_group_id if runtime is not None else None)
        ),
        aggregate=_build_lane_runtime_response("aggregate", aggregate_runtime),
        docgen=_build_lane_runtime_response("docgen", docgen_runtime),
        graph=_build_lane_runtime_response("graph", graph_runtime),
        docgen_preview=_build_runtime_preview(
            build_status=docgen_runtime,
            draft_markdown=draft_markdown,
            manifest=manifest,
        ),
        docgen_metrics=_build_runtime_metrics(build_status=docgen_runtime),
        graph_metrics=_build_graph_metrics(build_status=graph_runtime),
    )


def _build_confirmed_plan_payload(plan: ConfirmedBuildPlan) -> dict[str, Any]:
    payload = dict(plan.plan_json or {})
    payload.setdefault("subject_name", plan.subject_name)
    payload.setdefault("user_prompt", plan.user_prompt)
    payload.setdefault("digest_mode", plan.digest_mode)
    payload.setdefault("chapter_plan", list(plan.chapter_plan_json))
    payload.setdefault("build_constraints", dict(plan.build_constraints_json))
    payload.setdefault("plan_summary", plan.plan_summary)
    payload["selected_file_ids"] = list(plan.selected_file_ids_json)
    payload["planner_session_id"] = plan.planner_session_id
    payload["confirmed_plan_id"] = plan.id
    return normalize_digest_confirmed_plan_payload(payload)


def _load_confirmed_plan_payload(
    *,
    subject_id: str,
    user_id: str,
    confirmed_plan_id: str,
) -> tuple[ConfirmedBuildPlan, dict[str, Any]]:
    with managed_session() as session:
        plan = get_confirmed_build_plan(
            session,
            subject_id=subject_id,
            user_id=user_id,
            plan_id=confirmed_plan_id,
        )
    return plan, _build_confirmed_plan_payload(plan)


def trigger_docgen_build(
    session: Session,
    *,
    subject: Subject,
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

    conflict = inspect_subject_build_precheck(session, subject=subject)
    vector_status = resolve_subject_build_vector_status(
        session,
        subject=subject,
        embedding_resolution=embedding_resolution,
    )
    force_full_rebuild = bool(
        conflict is not None
        and conflict.requires_full_rebuild
        and vector_status.mode != "disabled"
    )
    if force_full_rebuild:
        clear_chunk_vector_metadata(session, subject_id=subject.id)
    planner_session_id = None
    digest_mode = None
    plan_summary = None
    chapter_progress: list[dict[str, object]] = []
    recent_events: list[dict[str, object]] = []
    cleaned_prompt = _clean_prompt(prompt)
    if not confirmed_plan_id:
        raise ConfirmedBuildPlanRequiredError("docs")

    plan = get_confirmed_build_plan(
        session,
        subject_id=subject.id,
        user_id=user_id,
        plan_id=confirmed_plan_id,
    )
    if plan.status == "building":
        raise SubjectBuildLockConflictError(subject.id)
    planner_session_id = plan.planner_session_id
    digest_mode = plan.digest_mode
    plan_summary = plan.plan_summary
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
        subject_id=subject.id,
        file_ids=list(plan.selected_file_ids_json),
        allow_empty=True,
    )
    plan_prompt = _clean_prompt(plan.user_prompt) or _clean_prompt(plan.plan_summary)
    if file_ids:
        logger.warning(
            "knowledge_build_file_selection_ignored_for_confirmed_plan",
            subject_id=subject.id,
            confirmed_plan_id=confirmed_plan_id,
            requested_file_id_count=len(file_ids),
        )
    if cleaned_prompt and plan_prompt and cleaned_prompt != plan_prompt:
        logger.warning(
            "knowledge_build_prompt_ignored_for_confirmed_plan",
            subject_id=subject.id,
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
    if not acquire_knowledge_build_lock(subject.id, build_lock):
        raise SubjectBuildLockConflictError(subject.id)
    subject_scope = build_subject_storage_scope(user_id=subject.user_id, subject_id=subject.id)
    _clear_docgen_staging_safely(subject.id, subject_scope=subject_scope)
    update_knowledge_build_lane_status(
        subject.id,
        lane="docgen",
        subject_scope=subject_scope,
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
        plan_summary=plan_summary,
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
        subject_id=subject.id,
        requested_at=requested_at.isoformat(),
        file_count=len(accepted_file_ids),
        force_full_rebuild=force_full_rebuild,
        vector_mode=vector_status.mode,
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        search_only_mode=search_only_mode,
        build_group_id=build_group_id,
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
    )
    return build_data, accepted_file_ids, build_group_id


async def run_docgen_background(
    *,
    subject_id: str,
    subject_name: str | None = None,
    file_ids: list[str],
    prompt: str | None,
    requested_at: datetime,
    build_group_id: str,
    planner_session_id: str | None = None,
    confirmed_plan_id: str | None = None,
    user_id: str | None = None,
    background_task_registry: Any | None = None,
) -> None:
    """后台执行 DocGen 构建生命周期。

    负责把 API 接受的构建请求转成一次真实 workflow run：加载 confirmed
    plan、运行 `run_docgen_workflow`、持久化知识文档、
    更新状态、按设置派发独立图谱同步任务并释放构建锁。异常处理也集中在这里，避免 API 层持有
    长任务细节。
    """

    from app.workflows.digest import run_docgen_workflow
    from app.shared.infra.knowledge.build_store import release_knowledge_build_lock
    from app.workflows.digest.kg_doc_sync.builds import run_graph_docs_sync_auto_build
    from app.workflows.digest.kg_doc_sync.lib.prefetch import cancel_docgen_kg_prefetch
    build_session_id = _new_build_session_id()
    confirmed_plan_payload = None
    resolved_digest_mode = None
    sync_graph_after_docgen = bool(get_settings().knowledge_graph.sync_after_docgen)
    graph_llm_snapshot = capture_llm_runtime_snapshot() if sync_graph_after_docgen else None
    docgen_published = False
    logger.info(
        "knowledge_build_background_started",
        subject_id=subject_id,
        requested_at=requested_at.isoformat(),
        file_count=len(file_ids),
        planner_session_id=planner_session_id,
        confirmed_plan_id=confirmed_plan_id,
        user_id=user_id,
        build_group_id=build_group_id,
    )
    if not confirmed_plan_id or not user_id:
        _write_docgen_status(
            subject_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            status="failed",
            stage="failed",
            build_session_id=build_session_id,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=resolved_digest_mode,
            error_message="confirmed_plan_required",
            draft_available=False,
        )
        logger.error("knowledge_build_failed_missing_confirmed_plan", subject_id=subject_id)
        release_knowledge_build_lock(subject_id)
        return

    plan, confirmed_plan_payload = _load_confirmed_plan_payload(
        subject_id=subject_id,
        user_id=user_id,
        confirmed_plan_id=confirmed_plan_id,
    )
    planner_session_id = planner_session_id or plan.planner_session_id
    resolved_digest_mode = plan.digest_mode
    subject_scope = build_subject_storage_scope(user_id=user_id, subject_id=subject_id)
    _mark_confirmed_plan_status(
        subject_id=subject_id,
        user_id=user_id,
        confirmed_plan_id=confirmed_plan_id,
        status="building",
    )
    try:
        _clear_docgen_staging_safely(subject_id, subject_scope=subject_scope)
        _write_docgen_status(
            subject_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            subject_scope=subject_scope,
            status="running",
            stage="prepare_shared",
            build_session_id=build_session_id,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=resolved_digest_mode,
            error_message=None,
            draft_available=False,
            source_file_ids=file_ids,
            prompt=prompt,
        )
        if sync_graph_after_docgen:
            _write_graph_status(
                subject_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                subject_scope=subject_scope,
                status="accepted",
                stage="queued_after_docgen",
                source_file_ids=file_ids,
                prompt=prompt,
                current_stage_description="知识文档发布后将自动开始图谱同步。",
            )
        else:
            _write_graph_status(
                subject_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                subject_scope=subject_scope,
                status="skipped",
                stage="disabled",
                source_file_ids=file_ids,
                prompt=prompt,
                current_stage_description="已关闭文档构建后自动图谱同步。",
            )
        result = await run_docgen_workflow(
            subject_id=subject_id,
            subject_name=subject_name,
            user_id=user_id,
            file_ids=file_ids,
            user_prompt=prompt,
            requested_at=requested_at,
            build_session_id=build_session_id,
            confirmed_plan=confirmed_plan_payload,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=resolved_digest_mode,
        )
        if result.failed:
            cancel_docgen_kg_prefetch(subject_id=subject_id, build_session_id=build_session_id)
            if sync_graph_after_docgen:
                _write_graph_status(
                    subject_id,
                    requested_at=requested_at,
                    build_group_id=build_group_id,
                    subject_scope=subject_scope,
                    status="skipped",
                    stage="blocked_by_docgen_failure",
                    current_stage_description="知识文档构建失败，未继续图谱同步。",
            )
            _clear_docgen_staging_safely(subject_id, subject_scope=subject_scope)
            _write_docgen_status(
                subject_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                subject_scope=subject_scope,
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
                subject_id=subject_id,
                user_id=user_id,
                confirmed_plan_id=confirmed_plan_id,
                status="failed",
            )
            logger.error("knowledge_build_failed", subject_id=subject_id, error=result.error.detail)
            return
        final_docgen_state = result.require_value()
        _write_docgen_status(
            subject_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            subject_scope=subject_scope,
            status="completed",
            stage="completed",
            build_session_id=build_session_id,
            planner_session_id=planner_session_id,
            confirmed_plan_id=confirmed_plan_id,
            digest_mode=resolved_digest_mode,
            error_message=None,
            draft_available=False,
            current_stage_description="知识文档已发布完成。",
        )
        docgen_published = True
        if sync_graph_after_docgen:
            graph_coro = run_graph_docs_sync_auto_build(
                subject_id=subject_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                build_session_id=build_session_id,
                file_ids=file_ids,
                prompt=prompt,
                llm_snapshot=graph_llm_snapshot,
                docgen_state=final_docgen_state,
                subject_scope=subject_scope,
            )
            if background_task_registry is not None:
                background_task_registry.spawn(
                    graph_coro,
                    kind="knowledge.build.graph",
                    subject_id=subject_id,
                    name=f"knowledge.build.graph:auto:{subject_id}",
                )
            else:
                graph_task = asyncio.create_task(graph_coro, name=f"knowledge.build.graph:auto:{subject_id}")

                def _log_graph_task_result(task: asyncio.Task[Any]) -> None:
                    if task.cancelled():
                        return
                    try:
                        exc = task.exception()
                    except asyncio.CancelledError:
                        return
                    if exc is not None:
                        logger.warning(
                            "knowledge_graph_auto_task_failed",
                            subject_id=subject_id,
                            error=str(exc),
                        )

                graph_task.add_done_callback(_log_graph_task_result)
            logger.info(
                "knowledge_graph_auto_build_spawned_after_docgen",
                subject_id=subject_id,
                build_group_id=build_group_id,
                registered=background_task_registry is not None,
            )
        else:
            _write_graph_status(
                subject_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                subject_scope=subject_scope,
                status="skipped",
                stage="disabled",
                source_file_ids=file_ids,
                prompt=prompt,
                current_stage_description="已关闭文档构建后自动图谱同步，可在知识图谱面板手动构建。",
            )
        _mark_confirmed_plan_status(
            subject_id=subject_id,
            user_id=user_id,
            confirmed_plan_id=confirmed_plan_id,
            status="completed",
        )
    except asyncio.CancelledError:
        cancel_docgen_kg_prefetch(subject_id=subject_id, build_session_id=build_session_id)
        if sync_graph_after_docgen and not docgen_published:
            _write_graph_status(
                subject_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                subject_scope=subject_scope,
                status="cancelled",
                stage="cancelled",
                error_message="build_cancelled",
                current_stage_description="图谱构建已取消。",
        )
        if not docgen_published:
            _clear_docgen_staging_safely(subject_id, subject_scope=subject_scope)
            _write_docgen_status(
                subject_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                subject_scope=subject_scope,
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
            subject_id=subject_id,
            user_id=user_id,
            confirmed_plan_id=confirmed_plan_id,
            status="completed" if docgen_published else "cancelled",
        )
        raise
    except Exception:
        cancel_docgen_kg_prefetch(subject_id=subject_id, build_session_id=build_session_id)
        if sync_graph_after_docgen and not docgen_published:
            _write_graph_status(
                subject_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                subject_scope=subject_scope,
                status="skipped",
                stage="blocked_by_docgen_failure",
                current_stage_description="知识文档构建异常失败，未完成图谱同步。",
        )
        if not docgen_published:
            _clear_docgen_staging_safely(subject_id, subject_scope=subject_scope)
            _write_docgen_status(
                subject_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                subject_scope=subject_scope,
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
            subject_id=subject_id,
            user_id=user_id,
            confirmed_plan_id=confirmed_plan_id,
            status="completed" if docgen_published else "failed",
        )
        logger.exception("knowledge_build_failed", subject_id=subject_id)
        return
    finally:
        release_knowledge_build_lock(subject_id)


def get_docgen_result(
    session: Session | None = None,
    *,
    subject_id: str,
    subject_scope: SubjectStorageScope | None = None,
) -> DocGenGetResponse:
    """组装知识文档页面轮询所需的当前状态。

    读取已发布 Markdown、构建中草稿、manifest、build status、preview 和
    LLM 统计；该函数不触发构建，只服务 `/knowledge/docs` 轮询查询。
    """

    cs = get_content_store()
    subject_scope = subject_scope or resolve_subject_storage_scope(subject_id, session=session)
    draft_key = subject_scope.knowledge_build_prefix() + "merged_knowledge_base.md"
    manifest = read_knowledge_manifest(subject_id, subject_scope=subject_scope)
    runtime = read_knowledge_build_runtime(subject_id, subject_scope=subject_scope)
    docgen_build_status = runtime.docgen_runtime if runtime is not None else None
    try:
        markdown, published_updated_at = _load_current_published_markdown(
            session,
            subject_id=subject_id,
            subject_scope=subject_scope,
            manifest=manifest,
        )
    except Exception as exc:
        logger.warning(
            "docgen_result_published_markdown_degraded",
            subject_id=subject_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        markdown, published_updated_at = "", None
    draft_markdown = normalize_mermaid_blocks(run_store_sync(cs.read_text, draft_key, default="") or "")
    updated_at = published_updated_at or (manifest.updated_at if manifest is not None else None)
    draft_updated_at = (
        docgen_build_status.draft_updated_at
        if docgen_build_status is not None and docgen_build_status.draft_updated_at is not None
        else None
    )
    source_file_ids: list[str] = list(manifest.source_file_ids) if manifest is not None else []
    try:
        build_response = _resolve_runtime_build_status(
            subject_id=subject_id,
            session=session,
            subject_scope=subject_scope,
        )
    except Exception as exc:
        logger.warning(
            "docgen_result_build_status_degraded",
            subject_id=subject_id,
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
            vector_status = get_subject_vector_status_by_id(db_session, subject_id)
    except Exception as exc:
        logger.warning(
            "docgen_result_vector_status_degraded",
            subject_id=subject_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        vector_status = SubjectVectorStatusResponse()

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
