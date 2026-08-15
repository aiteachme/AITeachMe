"""Build one chapter execution brief per LangGraph ``Send`` branch."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event
from app.shared.infra.workflow.context import WorkflowContext
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.chapter_execution_brief import (
    ChapterExecutionBriefError,
    build_chapter_execution_brief,
)
from app.workflows.digest.docgen.lib.models import (
    ChapterExecutionBrief,
    ChapterGenerationTaskSeed,
    DocGenContext,
    DocumentBackbone,
    HighConfidenceEvidenceUnit,
    clean_string_list,
)
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def _backbone_targets_for_chapter(
    backbone: DocumentBackbone,
    *,
    chapter_index: int,
) -> tuple[list[str], list[str], list[str]]:
    glossary_terms = [
        item.term
        for item in backbone.canonical_glossary
        if chapter_index in item.target_chapters
    ]
    claim_targets = [
        item.claim_text
        for item in backbone.canonical_claim_pool
        if item.target_chapter == chapter_index
    ]
    confusion_targets = [
        item.topic or item.contrast
        for item in backbone.confusion_map
        if chapter_index in item.target_chapters
    ]
    return (
        clean_string_list(glossary_terms, limit=12),
        clean_string_list(claim_targets, limit=12),
        clean_string_list(confusion_targets, limit=10),
    )


def _evidence_for_chapter(
    evidence_units: list[HighConfidenceEvidenceUnit],
    *,
    chapter_index: int,
) -> list[dict[str, object]]:
    selected = [
        item
        for item in evidence_units
        if not item.chapter_affinity or float(item.chapter_affinity.get(chapter_index, 0.0) or 0.0) > 0.0
    ]
    selected.sort(
        key=lambda item: (
            float(item.chapter_affinity.get(chapter_index, 0.0) or 0.0),
            float(item.confidence or 0.0),
        ),
        reverse=True,
    )
    return [item.model_dump(mode="json") for item in selected[:8]]


def _fallback_brief(task_seed: ChapterGenerationTaskSeed) -> ChapterExecutionBrief:
    return ChapterExecutionBrief(
        chapter_index=task_seed.chapter_index,
        writing_instructions=list(task_seed.style_rules),
        retrieval_queries=list(task_seed.retrieval_queries),
        fallback_used=True,
    )


def build_chapter_execution_briefs_node(*, context: WorkflowContext):
    """Generate the single brief carried by the current fan-out branch."""

    async def build_chapter_execution_briefs_node_impl(state: DocGenState) -> dict:
        started_at = perf_counter()
        raw_seed = state.get("chapter_task_seed")
        if not isinstance(raw_seed, dict):
            return {"error": "缺少当前章节的执行 brief seed。"}

        task_seed = ChapterGenerationTaskSeed.model_validate(raw_seed)
        backbone = DocumentBackbone.model_validate(state.get("document_backbone") or {})
        docgen_context = DocGenContext.model_validate(state.get("docgen_context") or {})
        evidence_units = [
            HighConfidenceEvidenceUnit.model_validate(item)
            for item in list(state.get("high_confidence_evidence_units") or [])
        ]
        glossary_terms, claim_targets, confusion_targets = _backbone_targets_for_chapter(
            backbone,
            chapter_index=task_seed.chapter_index,
        )

        await publish_docgen_progress(
            context,
            state=state,
            stage="chapter_execution_brief_started",
            payload={
                "chapter_index": task_seed.chapter_index,
                "title": task_seed.enhanced_title or task_seed.confirmed_title,
            },
        )
        try:
            brief = await build_chapter_execution_brief(
                course_name=docgen_context.course_name or str(state.get("course_name") or ""),
                digest_mode=docgen_context.digest_mode or str(state.get("digest_mode") or "systematic"),
                chapter=task_seed.model_dump(mode="json"),
                locked_title=task_seed.enhanced_title or task_seed.confirmed_title,
                intent_core=dict(state.get("intent_core") or {}),
                glossary_terms=glossary_terms,
                claim_targets=claim_targets,
                confusion_targets=confusion_targets,
                source_slices=[item.model_dump(mode="json") for item in task_seed.source_slices],
                evidence_items=_evidence_for_chapter(
                    evidence_units,
                    chapter_index=task_seed.chapter_index,
                ),
                plan=docgen_context.plan,
                docgen_history_brief=docgen_context.docgen_history_brief,
                learner_profile_text=str(state.get("learner_profile_text") or docgen_context.learner_profile_text),
                extra_metadata={
                    "build_session_id": state.get("build_session_id") or "",
                    "planner_session_id": state.get("planner_session_id") or "",
                    "confirmed_plan_id": state.get("confirmed_plan_id") or "",
                },
            )
        except ChapterExecutionBriefError:
            brief = _fallback_brief(task_seed)

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        title = task_seed.enhanced_title or task_seed.confirmed_title
        append_knowledge_build_recent_event(
            state["course_id"],
            requested_at=state["requested_at"],
            build_group_id=state.get("build_group_id") or None,
            event={
                "stage": "chapter_execution_brief_ready",
                "chapter_index": task_seed.chapter_index,
                "title": title,
                "summary": (
                    f"第 {task_seed.chapter_index} 章《{title}》执行 brief 已生成："
                    f"讲解阶段 {len(brief.teaching_outline)} 个，检索词 {len(brief.retrieval_queries)} 条。"
                ),
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="chapter_execution_brief_ready",
            payload={
                "chapter_index": task_seed.chapter_index,
                "title": title,
                "teaching_outline": list(brief.teaching_outline),
                "writing_instructions": list(brief.writing_instructions),
                "retrieval_queries": list(brief.retrieval_queries),
                "fallback_used": brief.fallback_used,
            },
        )
        return {
            "chapter_execution_brief_items": [brief.model_dump(mode="json")],
            "chapter_prepare_ms": elapsed_ms,
            "llm_calls_total": 1,
        }

    return build_chapter_execution_briefs_node_impl


__all__ = ["build_chapter_execution_briefs_node"]
