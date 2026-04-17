"""Confirm DocGen internal execution plan and prepare chapter fan-out."""

from __future__ import annotations

from time import perf_counter

from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.docgen.lib.chapter_generation import compose_chapter_generation_plan
from app.workflows.digest.docgen.lib.models import (
    DocGenContext,
    DocGenIntentProfile,
    EnhancedChapterOutline,
    FileMaterialSummary,
)
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def build_confirm_and_dispatch_node(*, context: WorkflowContext):
    async def confirm_and_dispatch_node(state: DocGenState) -> dict:
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
        chapters = list(state.get("chapter_assignments") or [])
        if not chapters:
            return {"error": "DocGen 内部确认失败：没有可分发章节。"}

        generation_plan = compose_chapter_generation_plan(
            docgen_context=docgen_context,
            confirmed_chapters=chapters,
            enhanced_outlines=outlines,
            intent_profile=intent_profile,
            file_summaries=file_summaries,
            plan_mismatch_warnings=list(state.get("plan_mismatch_warnings") or []),
        )
        tasks = [task.model_dump(mode="json") for task in generation_plan.chapters]
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="generating_chapters",
            digest_mode=state.get("digest_mode") or None,
            total_chunks=len(tasks),
            processed_chunks=0,
            current_chunk=0,
            current_stage_description=f"DocGen 执行计划已确认，开始并行生成 {len(tasks)} 个章节。",
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "docgen_dispatch_ready",
                "summary": f"DocGen 内部执行计划已收口，共 {len(tasks)} 章，开始章节生成。",
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
            "chapter_generation_plan": generation_plan.model_dump(mode="json"),
            "chapter_tasks": tasks,
            "dispatch_ms": elapsed_ms,
        }

    return confirm_and_dispatch_node


__all__ = ["build_confirm_and_dispatch_node"]
