"""Knowledge-graph background build orchestration."""

from __future__ import annotations

import asyncio
import contextvars
import uuid
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlmodel import Session

from app.models.course import Course
from app.repositories.knowledge.docgen_repo import get_current_published_docs
from app.schemas.knowledge import KnowledgeGraphBuildData
from app.shared.infra.database import managed_session
from app.shared.infra.exceptions import AITeachMeError, CourseBuildLockConflictError
from app.shared.infra.knowledge.build_store import (
    KnowledgeBuildLock,
    KnowledgeBuildRuntimeStatus,
    acquire_knowledge_build_lock,
    is_knowledge_build_lock_owner,
    read_knowledge_build_runtime,
    release_knowledge_build_lock,
    sanitize_knowledge_build_error_message,
    update_knowledge_build_lane_status,
)
from app.shared.infra.llm_support.common import (
    LLMRuntimeSnapshot,
    capture_llm_runtime_snapshot,
    use_llm_runtime_snapshot,
)
from app.shared.infra.storage import CourseStorageScope, build_course_storage_scope
from app.utils.time import ensure_utc_datetime, utcnow
from app.workflows.digest.common.build_lifecycle import (
    ACTIVE_KNOWLEDGE_BUILD_STATUSES,
    maintain_knowledge_build_lock_lease,
)
from app.workflows.digest.kg_doc_sync.lib.inputs import (
    build_knowledge_doc_sync_input_from_docgen_state,
    extract_doc_chapter_metadatas,
    load_knowledge_doc_sync_input,
    resolve_graph_input_paths,
)
from app.workflows.digest.kg_doc_sync.lib.prefetch import consume_docgen_kg_prefetch

logger = structlog.get_logger(__name__)

_STALE_ACCEPTED_GRAPH_STATUS_AFTER = timedelta(minutes=5)
_STALE_ACCEPTED_GRAPH_STAGES = {"queued_after_docgen", "manual_graph_requested"}


def _collect_graph_source_file_ids(structured_context: dict[str, object]) -> list[str]:
    """Resolve source file ids from persisted docs-sync context."""

    collected: list[str] = []
    seen: set[str] = set()
    chapters = structured_context.get("chapters")
    if not isinstance(chapters, list):
        return collected
    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        raw_ids = chapter.get("source_file_ids")
        if not isinstance(raw_ids, list):
            continue
        for raw_id in raw_ids:
            parsed = str(raw_id or "").strip()
            if not parsed or parsed in seen:
                continue
            seen.add(parsed)
            collected.append(parsed)
    return collected


def _is_active_build_status(status: str | None) -> bool:
    return str(status or "").strip() in ACTIVE_KNOWLEDGE_BUILD_STATUSES


def _is_stale_accepted_graph_status(status: KnowledgeBuildRuntimeStatus) -> bool:
    if str(status.status or "").strip() != "accepted":
        return False
    if str(status.stage or "").strip() not in _STALE_ACCEPTED_GRAPH_STAGES:
        return False
    requested_at = ensure_utc_datetime(status.requested_at or status.started_at)
    if requested_at is None:
        return False
    return utcnow() - requested_at >= _STALE_ACCEPTED_GRAPH_STATUS_AFTER


def _spawn_graph_build_task(
    background_task_registry: Any | None,
    coro,
    *,
    course_id: str,
    name: str,
) -> Any:
    if background_task_registry is not None:
        return background_task_registry.spawn(
            coro,
            kind="knowledge.build.graph",
            course_id=course_id,
            name=name,
        )

    task = asyncio.create_task(coro, name=name)

    def _log_graph_task_result(finished_task: asyncio.Task[Any]) -> None:
        if finished_task.cancelled():
            return
        try:
            exc = finished_task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.warning(
                "knowledge_graph_manual_task_failed",
                course_id=course_id,
                error=str(exc),
            )

    task.add_done_callback(_log_graph_task_result)
    return task


def _still_owns_knowledge_build_lock(
    *,
    course_id: str,
    build_group_id: str,
    course_scope: CourseStorageScope,
) -> bool:
    try:
        return is_knowledge_build_lock_owner(
            course_id,
            build_group_id=build_group_id,
            course_scope=course_scope,
        )
    except Exception as exc:
        logger.warning(
            "knowledge_graph_build_lock_owner_check_failed",
            course_id=course_id,
            build_group_id=build_group_id,
            error=str(exc),
        )
        return False


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


def _current_doc_version_no(
    course_id: str,
    *,
    course_scope: CourseStorageScope | None = None,
) -> int:
    del course_scope
    with managed_session() as session:
        docs = get_current_published_docs(session, course_id)
    return max((int(doc.version_no or doc.version or 0) for doc in docs), default=0)


def _schedule_exam_prewarm_after_completed_graph(
    *,
    course_id: str,
    build_revision_no: int,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
    background_task_registry: Any | None = None,
    scheduled_tasks: list[Any] | None = None,
) -> None:
    revision_no = int(build_revision_no or 0)
    if revision_no != 1:
        logger.info(
            "knowledge_graph_completed_exam_prewarm_skipped_non_initial_build",
            course_id=course_id,
            build_revision_no=build_revision_no,
        )
        return
    coro = _trigger_default_exam_prewarm_when_units_ready(
        course_id=course_id,
        min_build_revision_no=revision_no,
        wait_for_units_timeout_s=30.0,
        llm_snapshot=llm_snapshot,
    )
    task_name = f"exam.prewarm.completed_build:{course_id}:{revision_no}"

    if background_task_registry is not None:
        task = background_task_registry.spawn(
            coro,
            kind="exam.prewarm",
            course_id=course_id,
            name=task_name,
            dedupe_key=f"exam.prewarm.completed_build:{course_id}:default:{revision_no}",
        )
        if scheduled_tasks is not None:
            scheduled_tasks.append(task)
        return

    task = asyncio.create_task(coro, name=task_name, context=contextvars.Context())
    if scheduled_tasks is not None:
        scheduled_tasks.append(task)

    def _log_exam_prewarm_result(finished_task: asyncio.Task[None]) -> None:
        if finished_task.cancelled():
            logger.info(
                "knowledge_graph_completed_exam_prewarm_cancelled",
                course_id=course_id,
                build_revision_no=build_revision_no,
            )
            return
        try:
            exc = finished_task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.warning(
                "knowledge_graph_completed_exam_prewarm_task_failed",
                course_id=course_id,
                build_revision_no=build_revision_no,
                error=str(exc),
            )

    task.add_done_callback(_log_exam_prewarm_result)


def _base_doc_sync_metrics(
    *,
    knowledge_doc_source: str,
    chapter_count: int,
    doc_version_no: int,
) -> dict[str, int | str]:
    return {
        "knowledge_doc_source": knowledge_doc_source,
        "knowledge_doc_chapter_count": chapter_count,
        "doc_sync_unit_changes": 0,
        "doc_sync_edge_changes": 0,
        "doc_sync_elapsed_ms": 0,
        "elapsed_ms": 0,
        "revision_no": 0,
        "last_synced_doc_version_no": doc_version_no,
        "doc_sync_section_count": 0,
        "doc_sync_chapter_split_count": 0,
        "doc_sync_chapter_task_count": 0,
        "doc_sync_subsection_task_count": 0,
        "doc_sync_successful_section_count": 0,
        "doc_sync_failed_section_count": 0,
        "doc_sync_llm_section_count": 0,
        "doc_sync_llm_error_count": 0,
        "doc_sync_empty_llm_result_count": 0,
        "doc_sync_empty_repair_attempt_count": 0,
        "doc_sync_empty_repair_success_count": 0,
        "doc_sync_rule_fallback_attempt_count": 0,
        "doc_sync_rule_fallback_success_count": 0,
        "source_ref_count": 0,
        "backbone_unit_count": 0,
        "backbone_edge_count": 0,
        "stitched_edge_count": 0,
        "section_local_stitch_edge_count": 0,
        "mention_stitch_edge_count": 0,
        "graph_isolated_unit_count": 0,
        "graph_component_count": 0,
        "graph_largest_component_unit_count": 0,
        "graph_active_unit_count": 0,
        "graph_active_edge_count": 0,
        "graph_avg_degree": 0.0,
        "graph_isolated_unit_pct": 0.0,
        "stable_anchor_count": 0,
        "deprecated_unit_count": 0,
        "deprecated_edge_count": 0,
        "prefetch_section_count": 0,
        "prefetch_reused_section_count": 0,
        "prefetch_catchup_section_count": 0,
        "prefetch_stale_section_count": 0,
        "prefetch_failed_section_count": 0,
        "docgen_draft_fast_finalize": 0,
        "docgen_draft_final_unit_count": 0,
        "docgen_draft_final_edge_count": 0,
        "docgen_draft_final_skipped_edge_count": 0,
    }


def _completed_doc_sync_metrics(
    *,
    knowledge_doc_source: str,
    chapter_count: int,
    doc_version_no: int,
    sync_report,
) -> dict[str, int | str]:
    metrics = _base_doc_sync_metrics(
        knowledge_doc_source=knowledge_doc_source,
        chapter_count=chapter_count,
        doc_version_no=doc_version_no,
    )
    metrics.update(
        {
            "doc_sync_unit_changes": sync_report.unit_change_count,
            "doc_sync_edge_changes": sync_report.edge_change_count,
            "doc_sync_elapsed_ms": sync_report.elapsed_ms,
            "elapsed_ms": sync_report.elapsed_ms,
            "revision_no": sync_report.build_revision_no,
            "doc_sync_section_count": sync_report.section_count,
            "doc_sync_chapter_split_count": sync_report.chapter_split_count,
            "doc_sync_chapter_task_count": sync_report.chapter_task_count,
            "doc_sync_subsection_task_count": sync_report.subsection_task_count,
            "doc_sync_successful_section_count": sync_report.successful_section_count,
            "doc_sync_failed_section_count": sync_report.failed_section_count,
            "doc_sync_llm_section_count": sync_report.llm_section_count,
            "doc_sync_llm_error_count": sync_report.llm_error_count,
            "doc_sync_empty_llm_result_count": sync_report.empty_llm_result_count,
            "doc_sync_empty_repair_attempt_count": sync_report.empty_repair_attempt_count,
            "doc_sync_empty_repair_success_count": sync_report.empty_repair_success_count,
            "doc_sync_rule_fallback_attempt_count": sync_report.rule_fallback_attempt_count,
            "doc_sync_rule_fallback_success_count": sync_report.rule_fallback_success_count,
            "source_ref_count": sync_report.source_ref_count,
            "backbone_unit_count": sync_report.backbone_unit_count,
            "backbone_edge_count": sync_report.backbone_edge_count,
            "stitched_edge_count": sync_report.stitched_edge_count,
            "section_local_stitch_edge_count": sync_report.section_local_stitch_edge_count,
            "mention_stitch_edge_count": sync_report.mention_stitch_edge_count,
            "graph_isolated_unit_count": sync_report.graph_isolated_unit_count,
            "graph_component_count": sync_report.graph_component_count,
            "graph_largest_component_unit_count": sync_report.graph_largest_component_unit_count,
            "graph_active_unit_count": sync_report.graph_active_unit_count,
            "graph_active_edge_count": sync_report.graph_active_edge_count,
            "graph_avg_degree": sync_report.graph_avg_degree,
            "graph_isolated_unit_pct": sync_report.graph_isolated_unit_pct,
            "stable_anchor_count": sync_report.stable_anchor_count,
            "deprecated_unit_count": sync_report.deprecated_unit_count,
            "deprecated_edge_count": sync_report.deprecated_edge_count,
            "prefetch_section_count": sync_report.prefetch_section_count,
            "prefetch_reused_section_count": sync_report.prefetch_reused_section_count,
            "prefetch_catchup_section_count": sync_report.prefetch_catchup_section_count,
            "prefetch_stale_section_count": sync_report.prefetch_stale_section_count,
            "prefetch_failed_section_count": sync_report.prefetch_failed_section_count,
            "docgen_draft_fast_finalize": sync_report.docgen_draft_fast_finalize,
            "docgen_draft_final_unit_count": sync_report.docgen_draft_final_unit_count,
            "docgen_draft_final_edge_count": sync_report.docgen_draft_final_edge_count,
            "docgen_draft_final_skipped_edge_count": sync_report.docgen_draft_final_skipped_edge_count,
        }
    )
    return metrics


def trigger_graph_docs_sync_manual_build(
    session: Session,
    *,
    course: Course,
    background_task_registry: Any | None = None,
) -> KnowledgeGraphBuildData:
    """Accept and schedule a manual graph rebuild from published knowledge docs.

    This is the API-facing synchronous phase for `/knowledge/build/graph`.
    It validates runtime state, writes the graph lane accepted status and
    registers the cancellable background task. HTTP response wrapping stays in
    the API layer.
    """

    course_scope = build_course_storage_scope(user_id=course.user_id, course_id=course.id)
    runtime = read_knowledge_build_runtime(course.id, course_scope=course_scope)
    docgen_status = runtime.docgen_runtime if runtime is not None else None
    graph_status = runtime.graph_runtime if runtime is not None else None
    if docgen_status is not None and _is_active_build_status(docgen_status.status):
        raise AITeachMeError(
            detail="知识文档仍在构建中，请等待文档发布后再重建图谱。",
            error_code="DOCGEN_BUILD_IN_PROGRESS",
            status_code=409,
        )
    if graph_status is not None and _is_active_build_status(graph_status.status):
        if _is_stale_accepted_graph_status(graph_status):
            logger.warning(
                "knowledge_graph_stale_accepted_status_overridden",
                course_id=course.id,
                status=graph_status.status,
                stage=graph_status.stage,
                requested_at=graph_status.requested_at.isoformat(),
            )
        else:
            raise AITeachMeError(
                detail="知识图谱正在构建中。",
                error_code="GRAPH_BUILD_IN_PROGRESS",
                status_code=409,
            )

    sync_input = load_knowledge_doc_sync_input(
        course.id,
        session=session,
        course_scope=course_scope,
    )
    if not sync_input.markdown.strip():
        raise AITeachMeError(
            detail="当前还没有已发布的知识文档，请先完成知识文档构建。",
            error_code="KNOWLEDGE_DOC_REQUIRED_FOR_GRAPH_BUILD",
            status_code=422,
        )

    source_file_ids = _collect_graph_source_file_ids(sync_input.structured_context)
    prompt = docgen_status.prompt if docgen_status is not None else None
    requested_at = utcnow()
    build_group_id = uuid.uuid4().hex
    build_session_id = uuid.uuid4().hex
    doc_version_no = int(sync_input.structured_context.get("doc_version_no") or 0)
    chapters = sync_input.structured_context.get("chapters")
    chapter_count = len(chapters) if isinstance(chapters, list) else 0
    build_lock = KnowledgeBuildLock(
        requested_at=requested_at,
        build_group_id=build_group_id,
        source_file_ids=source_file_ids,
        prompt=prompt,
    )
    if not acquire_knowledge_build_lock(
        course.id,
        build_lock,
        course_scope=course_scope,
    ):
        raise CourseBuildLockConflictError(course.id)

    background_coro = None
    try:
        _write_graph_status(
            course.id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            course_scope=course_scope,
            status="accepted",
            stage="manual_graph_requested",
            build_session_id=build_session_id,
            error_message=None,
            source_file_ids=source_file_ids,
            prompt=prompt,
            metrics={
                "knowledge_doc_source": sync_input.source,
                "knowledge_doc_chapter_count": chapter_count,
                "last_synced_doc_version_no": doc_version_no,
                "graph_input_paths": ["knowledge_doc"] + (["source_files"] if source_file_ids else []),
            },
            current_stage_description="已接收图谱重建请求，准备读取当前知识文档。",
        )
        llm_snapshot = capture_llm_runtime_snapshot()
        background_coro = run_graph_docs_sync_manual_build(
            course_id=course.id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            build_session_id=build_session_id,
            file_ids=source_file_ids,
            prompt=prompt,
            llm_snapshot=llm_snapshot,
            course_scope=course_scope,
            background_task_registry=background_task_registry,
            manage_build_lock=True,
        )
        spawned_task = _spawn_graph_build_task(
            background_task_registry,
            background_coro,
            course_id=course.id,
            name=f"knowledge.build.graph:{course.id}:{build_group_id}",
        )
    except BaseException:
        close = getattr(background_coro, "close", None)
        if callable(close):
            close()
        release_knowledge_build_lock(
            course.id,
            build_group_id=build_group_id,
            course_scope=course_scope,
        )
        raise

    add_done_callback = getattr(spawned_task, "add_done_callback", None)
    if callable(add_done_callback):

        def _release_if_cancelled_before_cleanup(finished_task) -> None:
            if not finished_task.cancelled():
                return
            release_knowledge_build_lock(
                course.id,
                build_group_id=build_group_id,
                course_scope=course_scope,
            )

        add_done_callback(_release_if_cancelled_before_cleanup)
    logger.info(
        "knowledge_graph_build_request_accepted",
        course_id=course.id,
        user_id=course.user_id,
        requested_at=requested_at.isoformat(),
        build_group_id=build_group_id,
        build_session_id=build_session_id,
        source_file_count=len(source_file_ids),
        registered=background_task_registry is not None,
    )
    return KnowledgeGraphBuildData(
        course_id=course.id,
        status="accepted",
        requested_at=requested_at,
        build_group_id=build_group_id,
        build_session_id=build_session_id,
        source_file_ids=source_file_ids,
    )


async def run_graph_docs_sync_after_doc_build(
    *,
    course_id: str,
    requested_at: datetime,
    build_group_id: str,
    build_session_id: str,
    file_ids: list[str],
    prompt: str | None,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
    docgen_state: dict[str, object] | None = None,
    course_scope: CourseStorageScope | None = None,
    early_units_callback: object | None = None,
    embedded_in_parent_trace: bool = False,
    enforce_build_lock: bool = False,
) -> dict[str, int | str]:
    """Re-sync knowledge units and knowledge images from the latest knowledge document."""

    from app.workflows.digest.kg_doc_sync import run_graph_docs_sync_workflow

    sync_input = build_knowledge_doc_sync_input_from_docgen_state(
        course_id,
        docgen_state,
        course_scope=course_scope,
    )
    if sync_input is None:
        sync_input = load_knowledge_doc_sync_input(course_id, course_scope=course_scope)
    knowledge_doc_markdown = sync_input.markdown
    knowledge_doc_source = sync_input.source
    doc_chapter_metadatas = extract_doc_chapter_metadatas(knowledge_doc_markdown)
    doc_version_no = int(
        sync_input.structured_context.get("doc_version_no")
        or _current_doc_version_no(course_id, course_scope=course_scope)
    )
    base_metrics = _base_doc_sync_metrics(
        knowledge_doc_source=knowledge_doc_source,
        chapter_count=len(doc_chapter_metadatas),
        doc_version_no=doc_version_no,
    )
    prefetched_sections = []
    prefetch_metrics: dict[str, int | str] = {}
    if docgen_state is not None and build_session_id:
        prefetched_sections, prefetch_metrics = await consume_docgen_kg_prefetch(
            course_id=course_id,
            build_session_id=build_session_id,
        )
        base_metrics.update(prefetch_metrics)
    if enforce_build_lock and (
        course_scope is None
        or not _still_owns_knowledge_build_lock(
            course_id=course_id,
            build_group_id=build_group_id,
            course_scope=course_scope,
        )
    ):
        raise asyncio.CancelledError
    if not knowledge_doc_markdown.strip():
        return base_metrics

    _write_graph_status(
        course_id,
        requested_at=requested_at,
        build_group_id=build_group_id,
        course_scope=course_scope,
        status="running",
        stage="graph_docs_sync",
        build_session_id=build_session_id,
        error_message=None,
        draft_available=False,
        source_file_ids=file_ids,
        prompt=prompt,
        graph_input_paths=resolve_graph_input_paths(
            file_ids=file_ids,
            knowledge_doc_markdown=knowledge_doc_markdown,
        ),
        metrics={"processed_chunks": 0, **base_metrics},
        current_stage_description="正在从最新知识文档同步知识点、知识图像和关系。",
    )
    with use_llm_runtime_snapshot(llm_snapshot):
        sync_result = await run_graph_docs_sync_workflow(
            course_id=course_id,
            build_group_id=build_group_id,
            build_lock_phase="active" if enforce_build_lock else "published",
            markdown=knowledge_doc_markdown,
            build_revision_no=doc_version_no,
            build_session_id=build_session_id,
            structured_context=sync_input.structured_context,
            prefetched_sections=prefetched_sections,
            early_units_callback=early_units_callback,
            trace_metadata={
                "build_group_id": build_group_id,
                "doc_version_no": doc_version_no,
                "knowledge_doc_source": knowledge_doc_source,
                "chapter_count": len(doc_chapter_metadatas),
            },
            embedded_in_parent_trace=embedded_in_parent_trace,
        )
    if sync_result.failed:
        raise RuntimeError(sync_result.error.detail)

    sync_report = sync_result.require_value()
    completed_metrics = _completed_doc_sync_metrics(
        knowledge_doc_source=knowledge_doc_source,
        chapter_count=len(doc_chapter_metadatas),
        doc_version_no=doc_version_no,
        sync_report=sync_report,
    )
    completed_metrics.update(
        {
            key: value
            for key, value in prefetch_metrics.items()
            if key not in completed_metrics
        }
    )
    return completed_metrics


async def run_graph_docs_sync_manual_build(
    *,
    course_id: str,
    requested_at: datetime,
    build_group_id: str,
    build_session_id: str,
    file_ids: list[str],
    prompt: str | None,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
    course_scope: CourseStorageScope | None = None,
    background_task_registry: Any | None = None,
    manage_build_lock: bool = False,
) -> None:
    """Run a user-triggered graph rebuild from the latest persisted knowledge docs."""

    if manage_build_lock and course_scope is None:
        raise ValueError("course_scope is required when managing a knowledge build lock")

    build_lock_heartbeat: asyncio.Task[None] | None = None
    if manage_build_lock and course_scope is not None:
        owner_task = asyncio.current_task()
        if owner_task is not None:
            build_lock_heartbeat = asyncio.create_task(
                maintain_knowledge_build_lock_lease(
                    course_id=course_id,
                    build_group_id=build_group_id,
                    course_scope=course_scope,
                    owner_task=owner_task,
                ),
                name=f"knowledge.build.lock:{course_id}:{build_group_id}",
            )

    try:
        if build_lock_heartbeat is not None:
            await asyncio.sleep(0)
        if manage_build_lock and course_scope is not None and not _still_owns_knowledge_build_lock(
            course_id=course_id,
            build_group_id=build_group_id,
            course_scope=course_scope,
        ):
            return

        graph_status = await _run_graph_docs_sync_build(
            course_id=course_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            build_session_id=build_session_id,
            file_ids=file_ids,
            prompt=prompt,
            llm_snapshot=llm_snapshot,
            docgen_state=None,
            completed_description="知识图谱已同步完成。",
            cancelled_description="图谱构建已停止。",
            failure_log_event="knowledge_graph_manual_build_failed",
            course_scope=course_scope,
            embedded_in_parent_trace=False,
            enforce_build_lock=manage_build_lock,
        )
        if graph_status == "completed":
            _schedule_exam_prewarm_after_completed_graph(
                course_id=course_id,
                build_revision_no=_current_doc_version_no(course_id, course_scope=course_scope),
                llm_snapshot=llm_snapshot,
                background_task_registry=background_task_registry,
            )
    finally:
        if build_lock_heartbeat is not None:
            build_lock_heartbeat.cancel()
            try:
                await build_lock_heartbeat
            except asyncio.CancelledError:
                pass
        if manage_build_lock and course_scope is not None:
            release_knowledge_build_lock(
                course_id,
                build_group_id=build_group_id,
                course_scope=course_scope,
            )


async def run_graph_docs_sync_auto_build(
    *,
    course_id: str,
    requested_at: datetime,
    build_group_id: str,
    build_session_id: str,
    file_ids: list[str],
    prompt: str | None,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
    docgen_state: dict[str, object] | None = None,
    course_scope: CourseStorageScope | None = None,
    background_task_registry: Any | None = None,
) -> str:
    """Run an automatic graph sync after DocGen and return the final graph status."""

    exam_prewarm_tasks: list[Any] = []

    try:
        graph_status = await _run_graph_docs_sync_build(
            course_id=course_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            build_session_id=build_session_id,
            file_ids=file_ids,
            prompt=prompt,
            llm_snapshot=llm_snapshot,
            docgen_state=docgen_state,
            completed_description="知识图谱已自动同步完成。",
            cancelled_description="自动图谱同步已停止。",
            failure_log_event="knowledge_graph_auto_build_failed",
            course_scope=course_scope,
            early_units_callback=None,
            embedded_in_parent_trace=True,
        )
        if graph_status != "completed":
            for task in exam_prewarm_tasks:
                if not task.done():
                    task.cancel()
            logger.info(
                "knowledge_graph_auto_build_not_completed_after_exam_prewarm_dispatched",
                course_id=course_id,
                graph_status=graph_status,
                exam_prewarm_task_count=len(exam_prewarm_tasks),
            )
        if graph_status == "completed":
            _schedule_exam_prewarm_after_completed_graph(
                course_id=course_id,
                build_revision_no=_current_doc_version_no(course_id, course_scope=course_scope),
                llm_snapshot=llm_snapshot,
                background_task_registry=background_task_registry,
                scheduled_tasks=exam_prewarm_tasks,
            )
        return graph_status
    except asyncio.CancelledError:
        for task in exam_prewarm_tasks:
            if not task.done():
                task.cancel()
        raise


async def _run_graph_docs_sync_build(
    *,
    course_id: str,
    requested_at: datetime,
    build_group_id: str,
    build_session_id: str,
    file_ids: list[str],
    prompt: str | None,
    llm_snapshot: LLMRuntimeSnapshot | None,
    docgen_state: dict[str, object] | None,
    completed_description: str,
    cancelled_description: str,
    failure_log_event: str,
    course_scope: CourseStorageScope | None = None,
    early_units_callback: object | None = None,
    embedded_in_parent_trace: bool = False,
    enforce_build_lock: bool = False,
) -> str:
    doc_sync_metrics = _base_doc_sync_metrics(
        knowledge_doc_source="not_synced",
        chapter_count=0,
        doc_version_no=_current_doc_version_no(course_id, course_scope=course_scope),
    )
    try:
        doc_sync_metrics = await run_graph_docs_sync_after_doc_build(
            course_id=course_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            build_session_id=build_session_id,
            file_ids=file_ids,
            prompt=prompt,
            llm_snapshot=llm_snapshot,
            docgen_state=docgen_state,
            course_scope=course_scope,
            early_units_callback=early_units_callback,
            embedded_in_parent_trace=embedded_in_parent_trace,
            enforce_build_lock=enforce_build_lock,
        )
        failed_section_count = int(doc_sync_metrics.get("doc_sync_failed_section_count") or 0)
        completion_status = "partial_failed" if failed_section_count > 0 else "completed"
        completion_description = (
            f"知识图谱已部分同步完成，{failed_section_count} 个章节片段抽取失败，可稍后手动重试。"
            if failed_section_count > 0
            else completed_description
        )
        if enforce_build_lock and (
            course_scope is None
            or not _still_owns_knowledge_build_lock(
                course_id=course_id,
                build_group_id=build_group_id,
                course_scope=course_scope,
            )
        ):
            logger.warning(
                "knowledge_graph_terminal_status_skipped_after_lock_loss",
                course_id=course_id,
                build_group_id=build_group_id,
                status=completion_status,
            )
            return "cancelled"
        _write_graph_status(
            course_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            course_scope=course_scope,
            status=completion_status,
            stage=completion_status,
            error_message="kg_doc_sync_partial_failed" if failed_section_count > 0 else None,
            progress_pct=100,
            processed_chunks=0,
            current_stage_description=completion_description,
            metrics={"processed_chunks": 0, **doc_sync_metrics},
        )
        return completion_status
    except asyncio.CancelledError:
        if not enforce_build_lock or (
            course_scope is not None
            and _still_owns_knowledge_build_lock(
                course_id=course_id,
                build_group_id=build_group_id,
                course_scope=course_scope,
            )
        ):
            _write_graph_status(
                course_id,
                requested_at=requested_at,
                build_group_id=build_group_id,
                course_scope=course_scope,
                status="cancelled",
                stage="cancelled",
                error_message="build_cancelled",
                processed_chunks=0,
                current_stage_description=cancelled_description,
                metrics={"processed_chunks": 0, **doc_sync_metrics},
            )
        raise
    except Exception as exc:
        if enforce_build_lock and (
            course_scope is None
            or not _still_owns_knowledge_build_lock(
                course_id=course_id,
                build_group_id=build_group_id,
                course_scope=course_scope,
            )
        ):
            logger.warning(
                "knowledge_graph_failure_status_skipped_after_lock_loss",
                course_id=course_id,
                build_group_id=build_group_id,
                error=str(exc),
            )
            return "failed"
        graph_error_message = sanitize_knowledge_build_error_message(str(exc), build_kind="graph")
        _write_graph_status(
            course_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            course_scope=course_scope,
            status="failed",
            stage="failed",
            error_message=str(exc) or "build_crashed",
            processed_chunks=0,
            current_stage_description=graph_error_message,
            metrics={"processed_chunks": 0, **doc_sync_metrics},
        )
        logger.warning(failure_log_event, course_id=course_id, error=str(exc))
        return "failed"


async def _trigger_default_exam_prewarm_when_units_ready(
    *,
    course_id: str,
    min_build_revision_no: int,
    wait_for_units_timeout_s: float = 1800.0,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
) -> None:
    """知识点就绪后唤醒课程级、仅一次的首次测验任务。"""

    try:
        from app.workflows.examine.initial_exam import run_course_initial_exam_job

        with use_llm_runtime_snapshot(llm_snapshot):
            await run_course_initial_exam_job(
                course_id=course_id,
                build_session_id=f"knowledge-revision-{min_build_revision_no}",
            )
        logger.info(
            "knowledge_graph_auto_exam_prewarm_result",
            course_id=course_id,
            status="dispatched",
            min_build_revision_no=min_build_revision_no,
            wait_for_units_timeout_s=wait_for_units_timeout_s,
        )
    except Exception as exc:
        logger.warning(
            "knowledge_graph_auto_exam_prewarm_failed",
            course_id=course_id,
            error=str(exc),
        )


__all__ = [
    "run_graph_docs_sync_auto_build",
    "run_graph_docs_sync_after_doc_build",
    "run_graph_docs_sync_manual_build",
    "trigger_graph_docs_sync_manual_build",
]
