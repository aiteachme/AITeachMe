"""Confirm lightweight backbone seeds after title locking."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.chapter_planning import compose_seed_plan_and_backbone_agenda
from app.workflows.digest.docgen.lib.models import (
    DocGenContext,
    FileMaterialSummary,
    HighConfidenceEvidenceUnit,
    LockedChapterTitle,
    SourceAffinityByChapter,
)
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def build_confirm_and_seed_backbone_node(*, context: WorkflowContext):
    """构建骨架 seed 收口节点。"""

    async def confirm_and_seed_backbone_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        docgen_context = DocGenContext.model_validate(state.get("docgen_context") or {})
        locked_titles = [
            LockedChapterTitle.model_validate(item)
            for item in sorted(
                list(state.get("locked_titles") or []),
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
        evidence_units = [
            HighConfidenceEvidenceUnit.model_validate(item)
            for item in list(state.get("high_confidence_evidence_units") or [])
        ]
        chapters = list(state.get("chapter_assignments") or [])
        if not chapters:
            return {"error": "DocGen 内部确认失败：没有可生成骨架 seed 的章节。"}

        plan_seed, task_seeds, backbone_agenda = compose_seed_plan_and_backbone_agenda(
            docgen_context=docgen_context,
            confirmed_chapters=chapters,
            locked_titles=locked_titles,
            file_summaries=file_summaries,
            source_affinity_by_chapter=source_affinity,
            high_confidence_evidence_units=evidence_units,
            plan_mismatch_warnings=list(state.get("plan_mismatch_warnings") or []),
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="backbone_seed_ready",
            digest_mode=state.get("digest_mode") or None,
            total_chunks=len(task_seeds),
            processed_chunks=0,
            current_chunk=0,
            current_stage_description="章节标题已锁定，DocGen 骨架 seed 已确认，开始构建整本文档知识骨架。",
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "backbone_seed_ready",
                "summary": f"DocGen 骨架 seed 已确认，共 {len(task_seeds)} 章，开始构建知识骨架。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="backbone_seed_ready",
            payload={
                "chapter_count": len(task_seeds),
                "warning_count": len(plan_seed.plan_mismatch_warnings),
            },
        )
        return {
            "locked_titles": [item.model_dump(mode="json") for item in locked_titles],
            "chapter_generation_plan_seed": plan_seed.model_dump(mode="json"),
            "chapter_task_seeds": [item.model_dump(mode="json") for item in task_seeds],
            "backbone_research_agenda": backbone_agenda.model_dump(mode="json"),
            "seed_backbone_ms": elapsed_ms,
            "llm_calls_total": 0,
        }

    return confirm_and_seed_backbone_node


__all__ = ["build_confirm_and_seed_backbone_node"]
