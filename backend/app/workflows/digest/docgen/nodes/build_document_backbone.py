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
from app.workflows.digest.docgen.lib.pipeline_artifacts import (
    build_chapters_enhanced,
    build_dispatch_table,
    build_guideline,
    build_preliminary_kg,
)
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def _node_type_counts(preliminary_kg: dict[str, object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in list(preliminary_kg.get("nodes") or []):
        if not isinstance(item, dict):
            continue
        node_type = str(item.get("knowledge_unit_type") or "concept").strip() or "concept"
        counts[node_type] = counts.get(node_type, 0) + 1
    return counts


def _sample_nodes(preliminary_kg: dict[str, object]) -> list[dict[str, str]]:
    samples: list[dict[str, str]] = []
    for item in list(preliminary_kg.get("nodes") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        samples.append(
            {
                "name": name[:80],
                "type": str(item.get("knowledge_unit_type") or "concept").strip() or "concept",
                "summary": str(item.get("summary") or "").strip()[:160],
            }
        )
        if len(samples) >= 8:
            break
    return samples


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
            build_group_id=state.get("build_group_id") or None,
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

        guideline = build_guideline(
            document_backbone=document_backbone,
            writing_rules=plan_seed.writing_rules,
        )
        chapters_enhanced = build_chapters_enhanced(
            task_seeds=task_seeds,
            summary_enhanced=dict(state.get("summary_enhanced") or {}),
        )
        dispatch_table = build_dispatch_table(
            chapter_tasks=task_seeds,
            guideline=guideline,
            summary_enhanced=dict(state.get("summary_enhanced") or {}),
        )
        preliminary_kg = build_preliminary_kg(
            chapters_enhanced=chapters_enhanced,
            dispatch_table=dispatch_table,
            guideline=guideline,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            status="running",
            stage="preparing_chapter_execution_briefs",
            digest_mode=state.get("digest_mode") or None,
            total_chunks=len(task_seeds),
            processed_chunks=0,
            current_chunk=0,
            discovered_node_count=int(preliminary_kg.get("node_count", 0) or 0),
            discovered_node_types=_node_type_counts(preliminary_kg),
            sample_nodes=_sample_nodes(preliminary_kg),
            metrics={
                "docgen_preliminary_kg_node_count": int(preliminary_kg.get("node_count", 0) or 0),
                "docgen_preliminary_kg_edge_count": int(preliminary_kg.get("edge_count", 0) or 0),
                "docgen_preliminary_kg_stage": "document_backbone_ready",
            },
            current_stage_description=f"文档知识骨架已生成，开始并行准备 {len(task_seeds)} 个章节的执行 brief。",
        )
        append_knowledge_build_recent_event(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
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
                "preliminary_kg_node_count": int(preliminary_kg.get("node_count", 0) or 0),
                "preliminary_kg_edge_count": int(preliminary_kg.get("edge_count", 0) or 0),
                "warning_count": len(warnings),
                "fallback_used": document_backbone.fallback_used,
            },
        )
        return {
            "document_backbone": document_backbone.model_dump(mode="json"),
            "chapters_enhanced": chapters_enhanced,
            "dispatch_table": dispatch_table,
            "preliminary_kg": preliminary_kg,
            "guideline": guideline,
            "backbone_conflict_warnings": [item.model_dump(mode="json") for item in warnings],
            "backbone_ms": elapsed_ms,
        }

    return document_backbone_node


__all__ = ["build_document_backbone_node"]
