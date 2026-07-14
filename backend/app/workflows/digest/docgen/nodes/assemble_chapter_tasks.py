"""Assemble final chapter tasks after chapter execution briefs fan-in."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.chapter_planning import assemble_chapter_generation_plan
from app.workflows.digest.docgen.lib.document_backbone import apply_backbone_to_chapter_plan
from app.workflows.digest.docgen.lib.models import (
    ChapterExecutionBrief,
    ChapterGenerationTaskSeed,
    DocGenContext,
    DocGenIntentProfile,
    DocumentBackbone,
    FileMaterialSummary,
    LockedChapterTitle,
    SourceAffinityByChapter,
)
from app.workflows.digest.docgen.lib.pipeline_artifacts import (
    build_chapters_enhanced,
    build_dispatch_table,
    build_preliminary_kg,
)
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def build_assemble_chapter_tasks_node(*, context: WorkflowContext):
    """构建最终章节任务装配节点。"""

    async def assemble_chapter_tasks_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        docgen_context = DocGenContext.model_validate(state.get("docgen_context") or {})
        intent_profile = DocGenIntentProfile.model_validate(state.get("intent_profile") or {})
        document_backbone = DocumentBackbone.model_validate(state.get("document_backbone") or {})
        locked_titles = [
            LockedChapterTitle.model_validate(item)
            for item in list(state.get("locked_titles") or [])
        ]
        task_seeds = [
            ChapterGenerationTaskSeed.model_validate(item)
            for item in list(state.get("chapter_task_seeds") or [])
        ]
        chapter_briefs = [
            ChapterExecutionBrief.model_validate(item)
            for item in sorted(
                list(state.get("chapter_execution_briefs") or []),
                key=lambda raw: int((raw or {}).get("chapter_index", 0) or 0),
            )
        ]
        file_summaries = [
            FileMaterialSummary.model_validate(item)
            for item in list(state.get("file_summaries") or [])
        ]
        source_affinity = [
            SourceAffinityByChapter.model_validate(item)
            for item in list(state.get("source_affinity_by_chapter") or [])
        ]
        chapters = list(state.get("chapter_assignments") or [])
        if not chapters:
            return {"error": "没有可装配的章节任务。"}

        generation_plan = assemble_chapter_generation_plan(
            docgen_context=docgen_context,
            confirmed_chapters=chapters,
            locked_titles=locked_titles,
            intent_profile=intent_profile,
            file_summaries=file_summaries,
            source_affinity_by_chapter=source_affinity,
            task_seeds=task_seeds,
            chapter_execution_briefs=chapter_briefs,
            plan_mismatch_warnings=list(state.get("plan_mismatch_warnings") or []),
        )
        generation_plan = apply_backbone_to_chapter_plan(
            plan=generation_plan,
            backbone=document_backbone,
        )
        guideline = dict(state.get("guideline") or {})
        summary_enhanced = dict(state.get("summary_enhanced") or {})
        tasks = [task.model_dump(mode="json") for task in generation_plan.chapters]
        chapters_enhanced = build_chapters_enhanced(
            tasks=list(generation_plan.chapters),
            briefs=chapter_briefs,
            summary_enhanced=summary_enhanced,
        )
        dispatch_table = build_dispatch_table(
            chapter_tasks=list(generation_plan.chapters),
            guideline=guideline,
            summary_enhanced=summary_enhanced,
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            status="running",
            stage="generating_chapters",
            digest_mode=state.get("digest_mode") or None,
            total_chunks=len(tasks),
            processed_chunks=0,
            current_chunk=0,
            current_stage_description=f"章节执行 brief 已合并，开始并行生成 {len(tasks)} 个章节。",
        )
        append_knowledge_build_recent_event(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            event={
                "stage": "chapter_tasks_ready",
                "summary": f"最终章节任务已装配完成，共 {len(tasks)} 章，开始并行生成章节草稿。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="chapter_tasks_ready",
            payload={
                "chapter_count": len(tasks),
                "brief_count": len(chapter_briefs),
                "warning_count": len(generation_plan.plan_mismatch_warnings),
            },
        )
        return {
            "chapter_execution_briefs": [item.model_dump(mode="json") for item in chapter_briefs],
            "chapter_generation_plan": generation_plan.model_dump(mode="json"),
            "chapters_enhanced": chapters_enhanced,
            "dispatch_table": dispatch_table,
            "preliminary_kg": build_preliminary_kg(
                chapters_enhanced=chapters_enhanced,
                dispatch_table=dispatch_table,
                guideline=guideline,
            ),
            "chapter_tasks": tasks,
            "assemble_tasks_ms": elapsed_ms,
            "llm_calls_total": 0,
        }

    return assemble_chapter_tasks_node


__all__ = ["build_assemble_chapter_tasks_node"]
