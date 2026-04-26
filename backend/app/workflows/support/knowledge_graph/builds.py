"""Knowledge-graph background build orchestration."""

from __future__ import annotations

import uuid
from datetime import datetime

import structlog

from app.shared.infra.database import managed_session
from app.shared.infra.llm_support.common import (
    LLMRuntimeSnapshot,
    use_llm_runtime_snapshot,
)
from app.shared.infra.observability import langsmith_trace
from app.shared.infra.knowledge.build_store import (
    read_knowledge_manifest,
    update_knowledge_build_lane_status,
)
from app.workflows.digest.kg_file_ingest.lib.job_lifecycle import cleanup_pending_by_subject
from app.workflows.digest.kg_docs_sync.inputs import (
    extract_doc_chapter_metadatas,
    load_knowledge_doc_sync_input,
    resolve_graph_input_paths,
)

logger = structlog.get_logger()


def _end_trace_run(trace_run: object | None, outputs: dict[str, object]) -> None:
    if trace_run is not None:
        trace_run.end(outputs=outputs)


def _write_graph_status(subject: str, *, requested_at: datetime, status: str, stage: str, **extra: object) -> None:
    update_knowledge_build_lane_status(
        subject,
        lane="graph",
        requested_at=requested_at,
        status=status,
        stage=stage,
        **extra,
    )


def _new_graph_run_id() -> int:
    return (uuid.uuid4().int % 2_000_000_000) + 1


def _current_doc_version_no(subject: str) -> int:
    manifest = read_knowledge_manifest(subject)
    return int(manifest.version_no or 0) if manifest is not None else 0


def _cleanup_pending_digest_outputs(subject: str) -> None:
    try:
        with managed_session() as session:
            cleanup_pending_by_subject(session, subject=subject, job_type="graph")
    except Exception:
        logger.exception("knowledge_pending_cleanup_failed", subject=subject)


async def run_graph_docs_sync_after_doc_build(
    *,
    subject: str,
    requested_at: datetime,
    build_group_id: str,
    build_session_id: str,
    file_ids: list[int],
    prompt: str | None,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
) -> dict[str, int | str]:
    """Re-sync knowledge units and knowledge images from the latest knowledge document."""

    from app.workflows.digest.kg_docs_sync import run_graph_docs_sync_workflow

    with langsmith_trace(
        name="知识图谱同步：读取知识文档并入图",
        run_type="chain",
        inputs={
            "subject": subject,
            "file_count": len(file_ids),
            "prompt_present": bool((prompt or "").strip()),
        },
        subject=subject,
        build_session_id=build_session_id,
        workflow="digest.kg_docs_sync",
        lane="graph",
        extra_metadata={"build_group_id": build_group_id},
    ) as trace_run:
        sync_input = load_knowledge_doc_sync_input(subject)
        knowledge_doc_markdown = sync_input.markdown
        knowledge_doc_source = sync_input.source
        doc_chapter_metadatas = extract_doc_chapter_metadatas(knowledge_doc_markdown)
        doc_version_no = int(sync_input.structured_context.get("doc_version_no") or _current_doc_version_no(subject))
        if not knowledge_doc_markdown.strip():
            skipped_metrics = {
                "knowledge_doc_source": knowledge_doc_source,
                "knowledge_doc_chapter_count": len(doc_chapter_metadatas),
                "doc_sync_unit_changes": 0,
                "doc_sync_edge_changes": 0,
                "doc_sync_elapsed_ms": 0,
                "elapsed_ms": 0,
                "revision_no": 0,
                "last_synced_doc_version_no": doc_version_no,
                "doc_sync_section_count": 0,
                "doc_sync_llm_section_count": 0,
                "doc_sync_fallback_section_count": 0,
                "doc_sync_question_fallback_section_count": 0,
                "doc_sync_topic_fallback_section_count": 0,
                "source_ref_count": 0,
                "backbone_unit_count": 0,
                "backbone_edge_count": 0,
                "stable_anchor_count": 0,
                "deprecated_unit_count": 0,
                "deprecated_edge_count": 0,
            }
            _end_trace_run(trace_run, {"status": "skipped", **skipped_metrics})
            return skipped_metrics

        _write_graph_status(
            subject,
            requested_at=requested_at,
            build_group_id=build_group_id,
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
            metrics={
                "knowledge_doc_source": knowledge_doc_source,
                "knowledge_doc_chapter_count": len(doc_chapter_metadatas),
                "last_synced_doc_version_no": doc_version_no,
                "source_ref_count": 0,
                "backbone_unit_count": 0,
                "backbone_edge_count": 0,
                "stable_anchor_count": 0,
                "deprecated_unit_count": 0,
                "deprecated_edge_count": 0,
            },
            current_stage_description="正在从最新知识文档同步知识点、知识图像和关系。",
        )
        with use_llm_runtime_snapshot(llm_snapshot):
            sync_result = await run_graph_docs_sync_workflow(
                subject=subject,
                markdown=knowledge_doc_markdown,
                build_session_id=build_session_id,
                structured_context=sync_input.structured_context,
            )
        if sync_result.failed:
            _end_trace_run(trace_run, {"status": "failed", "error": sync_result.error.detail})
            raise RuntimeError(sync_result.error.detail)

        sync_report = sync_result.require_value()
        completed_metrics = {
            "knowledge_doc_source": knowledge_doc_source,
            "knowledge_doc_chapter_count": len(doc_chapter_metadatas),
            "doc_sync_unit_changes": sync_report.unit_change_count,
            "doc_sync_edge_changes": sync_report.edge_change_count,
            "doc_sync_elapsed_ms": sync_report.elapsed_ms,
            "elapsed_ms": sync_report.elapsed_ms,
            "revision_no": sync_report.build_revision_no,
            "last_synced_doc_version_no": doc_version_no,
            "doc_sync_section_count": sync_report.section_count,
            "doc_sync_llm_section_count": sync_report.llm_section_count,
            "doc_sync_fallback_section_count": sync_report.fallback_section_count,
            "doc_sync_question_fallback_section_count": sync_report.question_fallback_section_count,
            "doc_sync_topic_fallback_section_count": sync_report.topic_fallback_section_count,
            "source_ref_count": sync_report.source_ref_count,
            "backbone_unit_count": sync_report.backbone_unit_count,
            "backbone_edge_count": sync_report.backbone_edge_count,
            "stable_anchor_count": sync_report.stable_anchor_count,
            "deprecated_unit_count": sync_report.deprecated_unit_count,
            "deprecated_edge_count": sync_report.deprecated_edge_count,
        }
        _end_trace_run(trace_run, {"status": "completed", **completed_metrics})
        return completed_metrics


async def run_graph_file_ingest_background(
    *,
    subject: str,
    file_ids: list[int],
    prompt: str | None,
    requested_at: datetime,
    build_group_id: str,
    build_session_id: str,
    doc_chapter_metadatas: list[dict[str, object]] | None = None,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
) -> dict[str, int]:
    """Build graph candidates from parsed files without owning the outer build lock."""

    from app.workflows.digest.kg_file_ingest import run_graph_file_ingest_workflow

    with langsmith_trace(
        name="知识图谱摄取：文件解析结果入图",
        run_type="chain",
        inputs={
            "subject": subject,
            "file_count": len(file_ids),
            "prompt_present": bool((prompt or "").strip()),
            "chapter_metadata_count": len(doc_chapter_metadatas or []),
        },
        subject=subject,
        build_session_id=build_session_id,
        workflow="digest.kg_file_ingest",
        lane="graph",
        extra_metadata={"build_group_id": build_group_id},
    ) as trace_run:
        if not file_ids:
            skipped_metrics = {"processed_chunks": 0}
            _end_trace_run(trace_run, {"status": "skipped", **skipped_metrics})
            return skipped_metrics

        _write_graph_status(
            subject,
            requested_at=requested_at,
            build_group_id=build_group_id,
            status="running",
            stage="graph_file_ingest",
            build_session_id=build_session_id,
            error_message=None,
            draft_available=False,
            source_file_ids=file_ids,
            prompt=prompt,
            current_stage_description="正在从已解析文件抽取候选并构建图谱。",
        )
        _cleanup_pending_digest_outputs(subject)
        with use_llm_runtime_snapshot(llm_snapshot):
            result = await run_graph_file_ingest_workflow(
                subject=subject,
                job_id=_new_graph_run_id(),
                file_ids=file_ids,
                user_prompt=prompt,
                build_session_id=build_session_id,
                doc_chapter_metadatas=doc_chapter_metadatas,
            )
        if result.failed:
            if result.error.detail == "no_ready_digest_inputs":
                skipped_metrics = {"processed_chunks": 0}
                _end_trace_run(
                    trace_run,
                    {
                        "status": "skipped",
                        "reason": result.error.detail,
                        **skipped_metrics,
                    },
                )
                return skipped_metrics
            _end_trace_run(trace_run, {"status": "failed", "error": result.error.detail})
            raise RuntimeError(result.error.detail)

        final_state = result.require_value()
        completed_metrics = {"processed_chunks": len(final_state.get("chunk_ids", []))}
        _end_trace_run(trace_run, {"status": "completed", **completed_metrics})
        return completed_metrics


__all__ = [
    "run_graph_docs_sync_after_doc_build",
    "run_graph_file_ingest_background",
]
