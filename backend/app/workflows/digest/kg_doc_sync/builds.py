"""Knowledge-graph background build orchestration."""

from __future__ import annotations

from datetime import datetime

from app.shared.infra.llm_support.common import (
    LLMRuntimeSnapshot,
    use_llm_runtime_snapshot,
)
from app.shared.infra.observability import langsmith_trace
from app.shared.infra.knowledge.build_store import (
    read_knowledge_manifest,
    update_knowledge_build_lane_status,
)
from app.workflows.digest.kg_doc_sync.inputs import (
    extract_doc_chapter_metadatas,
    load_knowledge_doc_sync_input,
    resolve_graph_input_paths,
)


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


def _current_doc_version_no(subject: str) -> int:
    manifest = read_knowledge_manifest(subject)
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
        "doc_sync_llm_section_count": 0,
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
            "doc_sync_llm_section_count": sync_report.llm_section_count,
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
    subject: str,
    requested_at: datetime,
    build_group_id: str,
    build_session_id: str,
    file_ids: list[int],
    prompt: str | None,
    llm_snapshot: LLMRuntimeSnapshot | None = None,
) -> dict[str, int | str]:
    """Re-sync knowledge units and knowledge images from the latest knowledge document."""

    from app.workflows.digest.kg_doc_sync import run_graph_docs_sync_workflow

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
        workflow="digest.kg_doc_sync",
        lane="graph",
        extra_metadata={"build_group_id": build_group_id},
    ) as trace_run:
        sync_input = load_knowledge_doc_sync_input(subject)
        knowledge_doc_markdown = sync_input.markdown
        knowledge_doc_source = sync_input.source
        doc_chapter_metadatas = extract_doc_chapter_metadatas(knowledge_doc_markdown)
        doc_version_no = int(sync_input.structured_context.get("doc_version_no") or _current_doc_version_no(subject))
        if not knowledge_doc_markdown.strip():
            skipped_metrics = _base_doc_sync_metrics(
                knowledge_doc_source=knowledge_doc_source,
                chapter_count=len(doc_chapter_metadatas),
                doc_version_no=doc_version_no,
            )
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
        completed_metrics = _completed_doc_sync_metrics(
            knowledge_doc_source=knowledge_doc_source,
            chapter_count=len(doc_chapter_metadatas),
            doc_version_no=doc_version_no,
            sync_report=sync_report,
        )
        _end_trace_run(trace_run, {"status": "completed", **completed_metrics})
        return completed_metrics


__all__ = [
    "run_graph_docs_sync_after_doc_build",
]
