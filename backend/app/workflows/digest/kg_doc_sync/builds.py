"""Knowledge-graph background build orchestration."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import structlog

from app.shared.infra.llm_support.common import (
    LLMRuntimeSnapshot,
    use_llm_runtime_snapshot,
)
from app.shared.infra.observability.trace import langsmith_trace
from app.shared.infra.storage import SubjectStorageScope
from app.shared.infra.knowledge.build_store import (
    read_knowledge_manifest,
    sanitize_knowledge_build_error_message,
    update_knowledge_build_lane_status,
)
from app.workflows.digest.kg_doc_sync.inputs import (
    build_knowledge_doc_sync_input_from_docgen_state,
    extract_doc_chapter_metadatas,
    load_knowledge_doc_sync_input,
    resolve_graph_input_paths,
)
from app.workflows.digest.kg_doc_sync.graph import RUN_NAME_KG_DOC_SYNC

logger = structlog.get_logger(__name__)


def _end_trace_run(trace_run: Any | None, outputs: dict[str, Any]) -> None:
    if trace_run is not None:
        trace_run.end(outputs=outputs)


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


def _current_doc_version_no(
    subject_id: str,
    *,
    subject_scope: SubjectStorageScope | None = None,
) -> int:
    manifest = read_knowledge_manifest(subject_id, subject_scope=subject_scope)
    return int(manifest.version_no or 0) if manifest is not None else 0


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
        "source_ref_count": 0,
        "backbone_unit_count": 0,
        "backbone_edge_count": 0,
        "stable_anchor_count": 0,
        "deprecated_unit_count": 0,
        "deprecated_edge_count": 0,
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
            "source_ref_count": sync_report.source_ref_count,
            "backbone_unit_count": sync_report.backbone_unit_count,
            "backbone_edge_count": sync_report.backbone_edge_count,
            "stable_anchor_count": sync_report.stable_anchor_count,
            "deprecated_unit_count": sync_report.deprecated_unit_count,
            "deprecated_edge_count": sync_report.deprecated_edge_count,
        }
    )
    return metrics


async def run_graph_docs_sync_after_doc_build(
    *,
    subject_id: str,
    requested_at: datetime,
    build_group_id: str,
    build_session_id: str,
    file_ids: list[int],
    prompt: str | None,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
    docgen_state: dict[str, object] | None = None,
    subject_scope: SubjectStorageScope | None = None,
) -> dict[str, int | str]:
    """Re-sync knowledge units and knowledge images from the latest knowledge document."""

    from app.workflows.digest.kg_doc_sync import run_graph_docs_sync_workflow

    sync_input = build_knowledge_doc_sync_input_from_docgen_state(
        subject_id,
        docgen_state,
        subject_scope=subject_scope,
    )
    if sync_input is None:
        sync_input = load_knowledge_doc_sync_input(subject_id, subject_scope=subject_scope)
    knowledge_doc_markdown = sync_input.markdown
    knowledge_doc_source = sync_input.source
    doc_chapter_metadatas = extract_doc_chapter_metadatas(knowledge_doc_markdown)
    doc_version_no = int(
        sync_input.structured_context.get("doc_version_no")
        or _current_doc_version_no(subject_id, subject_scope=subject_scope)
    )
    base_metrics = _base_doc_sync_metrics(
        knowledge_doc_source=knowledge_doc_source,
        chapter_count=len(doc_chapter_metadatas),
        doc_version_no=doc_version_no,
    )
    if not knowledge_doc_markdown.strip():
        return base_metrics

    _write_graph_status(
        subject_id,
        requested_at=requested_at,
        build_group_id=build_group_id,
        subject_scope=subject_scope,
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
    with langsmith_trace(
        name=RUN_NAME_KG_DOC_SYNC,
        run_type="chain",
        subject_id=subject_id,
        build_session_id=build_session_id,
        workflow="digest.kg_doc_sync",
        lane="kg_doc_sync",
        inputs={
            "subject_id": subject_id,
            "build_group_id": build_group_id,
            "knowledge_doc_source": knowledge_doc_source,
            "chapter_count": len(doc_chapter_metadatas),
            "doc_version_no": doc_version_no,
        },
        extra_metadata={
            "build_group_id": build_group_id,
            "doc_version_no": doc_version_no,
            "knowledge_doc_source": knowledge_doc_source,
        },
        extra_tags=["workflow:digest.kg_doc_sync", "lane:kg_doc_sync"],
    ) as trace_run:
        with use_llm_runtime_snapshot(llm_snapshot):
            sync_result = await run_graph_docs_sync_workflow(
                subject_id=subject_id,
                markdown=knowledge_doc_markdown,
                build_session_id=build_session_id,
                structured_context=sync_input.structured_context,
            )
        if sync_result.failed:
            _end_trace_run(trace_run, {"status": "failed", "error": sync_result.error.detail})
            raise RuntimeError(sync_result.error.detail)

        sync_report = sync_result.require_value()
        completed_metrics = _completed_doc_sync_metrics(
            knowledge_doc_source=knowledge_doc_source,
            chapter_count=len(doc_chapter_metadatas),
            doc_version_no=doc_version_no,
            sync_report=sync_report,
        )
        _end_trace_run(trace_run, {"status": "completed", **completed_metrics})
        return completed_metrics


async def run_graph_docs_sync_manual_build(
    *,
    subject_id: str,
    requested_at: datetime,
    build_group_id: str,
    build_session_id: str,
    file_ids: list[int],
    prompt: str | None,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
    subject_scope: SubjectStorageScope | None = None,
) -> None:
    """Run a user-triggered graph rebuild from the latest persisted knowledge docs."""

    await _run_graph_docs_sync_build(
        subject_id=subject_id,
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
        subject_scope=subject_scope,
    )


async def run_graph_docs_sync_auto_build(
    *,
    subject_id: str,
    requested_at: datetime,
    build_group_id: str,
    build_session_id: str,
    file_ids: list[int],
    prompt: str | None,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
    docgen_state: dict[str, object] | None = None,
    subject_scope: SubjectStorageScope | None = None,
) -> None:
    """Run an automatic graph sync after DocGen without blocking the doc lane."""

    await _run_graph_docs_sync_build(
        subject_id=subject_id,
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
        subject_scope=subject_scope,
    )


async def _run_graph_docs_sync_build(
    *,
    subject_id: str,
    requested_at: datetime,
    build_group_id: str,
    build_session_id: str,
    file_ids: list[int],
    prompt: str | None,
    llm_snapshot: LLMRuntimeSnapshot | None,
    docgen_state: dict[str, object] | None,
    completed_description: str,
    cancelled_description: str,
    failure_log_event: str,
    subject_scope: SubjectStorageScope | None = None,
) -> None:
    doc_sync_metrics = _base_doc_sync_metrics(
        knowledge_doc_source="not_synced",
        chapter_count=0,
        doc_version_no=_current_doc_version_no(subject_id, subject_scope=subject_scope),
    )
    try:
        doc_sync_metrics = await run_graph_docs_sync_after_doc_build(
            subject_id=subject_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            build_session_id=build_session_id,
            file_ids=file_ids,
            prompt=prompt,
            llm_snapshot=llm_snapshot,
            docgen_state=docgen_state,
            subject_scope=subject_scope,
        )
        failed_section_count = int(doc_sync_metrics.get("doc_sync_failed_section_count") or 0)
        completion_status = "partial_failed" if failed_section_count > 0 else "completed"
        completion_description = (
            f"知识图谱已部分同步完成，{failed_section_count} 个章节片段抽取失败，可稍后手动重试。"
            if failed_section_count > 0
            else completed_description
        )
        _write_graph_status(
            subject_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            subject_scope=subject_scope,
            status=completion_status,
            stage=completion_status,
            error_message="kg_doc_sync_partial_failed" if failed_section_count > 0 else None,
            progress_pct=100,
            processed_chunks=0,
            current_stage_description=completion_description,
            metrics={"processed_chunks": 0, **doc_sync_metrics},
        )
    except asyncio.CancelledError:
        _write_graph_status(
            subject_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            subject_scope=subject_scope,
            status="cancelled",
            stage="cancelled",
            error_message="build_cancelled",
            processed_chunks=0,
            current_stage_description=cancelled_description,
            metrics={"processed_chunks": 0, **doc_sync_metrics},
        )
        raise
    except Exception as exc:
        graph_error_message = sanitize_knowledge_build_error_message(str(exc), build_kind="graph")
        _write_graph_status(
            subject_id,
            requested_at=requested_at,
            build_group_id=build_group_id,
            subject_scope=subject_scope,
            status="failed",
            stage="failed",
            error_message=str(exc) or "build_crashed",
            processed_chunks=0,
            current_stage_description=graph_error_message,
            metrics={"processed_chunks": 0, **doc_sync_metrics},
        )
        logger.warning(failure_log_event, subject_id=subject_id, error=str(exc))


__all__ = [
    "run_graph_docs_sync_auto_build",
    "run_graph_docs_sync_after_doc_build",
    "run_graph_docs_sync_manual_build",
]
