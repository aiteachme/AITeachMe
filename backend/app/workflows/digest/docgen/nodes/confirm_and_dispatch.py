"""Confirm DocGen internal execution plan and prepare chapter fan-out."""

from __future__ import annotations

from time import perf_counter

from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.lib.chapter_generation import (
    build_plan_seed_and_backbone_agenda,
    compose_chapter_generation_plan,
)
from app.workflows.digest.docgen.lib.models import (
    DocGenContext,
    DocGenIntentProfile,
    EnhancedChapterOutline,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    SourceAffinityByChapter,
)
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def build_confirm_and_dispatch_node(*, context: WorkflowContext):
    """构建 DocGen 内部派发节点。

    该节点把 prepare_context 的大纲、意图、文件摘要和证据候选合并成
    章节执行计划 seed，并生成后续 build_document_backbone 需要的议程。
    """

    async def confirm_and_dispatch_node(state: DocGenState) -> dict:
        """收口准备阶段产物，生成章节任务和骨架研究议程。"""

        started_at = perf_counter()
        docgen_context = DocGenContext.model_validate(state.get("docgen_context") or {})
        intent_profile = DocGenIntentProfile.model_validate(state.get("intent_profile") or {})
        outlines = [
            EnhancedChapterOutline.model_validate(item)
            for item in list(state.get("enhanced_chapter_outlines") or [])
        ]
        file_summaries = [
            FileMaterialSummary.model_validate(item)
            for item in list(state.get("file_summaries") or [])
        ]
        source_affinity = [
            SourceAffinityByChapter.model_validate(item)
            for item in list(state.get("source_affinity_by_chapter") or [])
        ]
        evidence_units = [
            HighConfidenceEvidenceUnit.model_validate(item)
            for item in list(state.get("high_confidence_evidence_units") or [])
        ]
        chapters = list(state.get("chapter_assignments") or [])
        if not chapters:
            return {"error": "DocGen 内部确认失败：没有可分发章节。"}

        generation_plan = compose_chapter_generation_plan(
            docgen_context=docgen_context,
            confirmed_chapters=chapters,
            enhanced_outlines=outlines,
            intent_profile=intent_profile,
            file_summaries=file_summaries,
            source_affinity_by_chapter=source_affinity,
            plan_mismatch_warnings=list(state.get("plan_mismatch_warnings") or []),
        )
        plan_seed, task_seeds, backbone_agenda = build_plan_seed_and_backbone_agenda(
            generation_plan=generation_plan,
            high_confidence_evidence_units=evidence_units,
            file_summaries=file_summaries,
        )
        tasks = [task.model_dump(mode="json") for task in generation_plan.chapters]
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="dispatch_ready",
            digest_mode=state.get("digest_mode") or None,
            total_chunks=len(tasks),
            processed_chunks=0,
            current_chunk=0,
            current_stage_description=f"DocGen 执行计划 seed 已确认，开始构建整本文档知识骨架。",
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "docgen_dispatch_ready",
                "summary": f"DocGen 内部执行计划 seed 已收口，共 {len(tasks)} 章，开始构建知识骨架。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="docgen_dispatch_ready",
            payload={
                "chapter_count": len(tasks),
                "source_policy": generation_plan.source_policy,
                "plan_mismatch_warning_count": len(generation_plan.plan_mismatch_warnings),
            },
        )
        return {
            "chapter_generation_plan_seed": plan_seed.model_dump(mode="json"),
            "chapter_task_seeds": [item.model_dump(mode="json") for item in task_seeds],
            "backbone_research_agenda": backbone_agenda.model_dump(mode="json"),
            "chapter_generation_plan": generation_plan.model_dump(mode="json"),
            "chapter_tasks": tasks,
            "dispatch_ms": elapsed_ms,
        }

    return confirm_and_dispatch_node


__all__ = ["build_confirm_and_dispatch_node"]
