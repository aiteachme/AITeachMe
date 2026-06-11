"""Build the document-level knowledge backbone."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.document_backbone import (
    build_document_backbone,
)
from app.workflows.digest.docgen.lib.models import (
    BackboneResearchAgenda,
    ChapterGenerationPlanSeed,
    ChapterGenerationTaskSeed,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
)
from app.workflows.digest.docgen.lib.pipeline_artifacts import build_guideline
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def build_document_backbone_node(*, context: WorkflowContext):
    """构建文档级知识骨架节点。

    读取章节 seed、资料摘要和高置信证据候选，生成整本文档的术语、
    主张、概念依赖和易混点，再把这些全局约束回填到每章任务。
    """

    async def document_backbone_node(state: DocGenState) -> dict:
        """生成 DocumentBackbone。"""

        started_at = perf_counter()
        task_seeds = [
            ChapterGenerationTaskSeed.model_validate(item)
            for item in list(state.get("chapter_task_seeds") or [])
        ]
        if not task_seeds:
            return {"error": "DocGen 知识骨架构建失败：缺少章节 seed。"}
        agenda = BackboneResearchAgenda.model_validate(state.get("backbone_research_agenda") or {})
        evidence_units = [
            HighConfidenceEvidenceUnit.model_validate(item)
            for item in list(state.get("high_confidence_evidence_units") or [])
        ]
        file_summaries = [
            FileMaterialSummary.model_validate(item)
            for item in list(state.get("file_summaries") or [])
        ]
        plan_seed = ChapterGenerationPlanSeed.model_validate(state.get("chapter_generation_plan_seed") or {})
        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            status="running",
            stage="building_document_backbone",
            digest_mode=state.get("digest_mode") or None,
            current_stage_description="正在统一术语、主张、证据和易混点，构建整本文档知识骨架。",
        )
        document_backbone, warnings = build_document_backbone(
            task_seeds=task_seeds,
            agenda=agenda,
            evidence_units=evidence_units,
            file_summaries=file_summaries,
        )

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            status="running",
            stage="preparing_chapter_execution_briefs",
            digest_mode=state.get("digest_mode") or None,
            total_chunks=len(task_seeds),
            processed_chunks=0,
            current_chunk=0,
            current_stage_description=f"文档知识骨架已生成，开始并行准备 {len(task_seeds)} 个章节的执行 brief。",
        )
        append_knowledge_build_recent_event(
            state["course_id"],
            requested_at=state["requested_at"],
            event={
                "stage": "document_backbone_ready",
                "summary": f"整本文档知识骨架已生成：术语 {len(document_backbone.canonical_glossary)} 个，主张 {len(document_backbone.canonical_claim_pool)} 条。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="document_backbone_ready",
            payload={
                "glossary_count": len(document_backbone.canonical_glossary),
                "claim_count": len(document_backbone.canonical_claim_pool),
                "confusion_count": len(document_backbone.confusion_map),
                "warning_count": len(warnings),
                "fallback_used": document_backbone.fallback_used,
            },
        )
        return {
            "document_backbone": document_backbone.model_dump(mode="json"),
            "guideline": build_guideline(
                document_backbone=document_backbone,
                writing_rules=plan_seed.writing_rules,
            ),
            "backbone_conflict_warnings": [item.model_dump(mode="json") for item in warnings],
            "backbone_ms": elapsed_ms,
        }

    return document_backbone_node


__all__ = ["build_document_backbone_node"]
