"""Build chapter execution briefs in parallel after backbone construction."""

from __future__ import annotations

from time import perf_counter
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.models import (
    ChapterExecutionBrief,
    ChapterGenerationTaskSeed,
    DocumentBackbone,
    clean_string_list,
)
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def _build_deterministic_brief(
    task_seed: ChapterGenerationTaskSeed,
    *,
    document_backbone: DocumentBackbone,
) -> ChapterExecutionBrief:
    """Compile the chapter contract without asking another model to reinterpret it."""

    chapter_index = task_seed.chapter_index
    title = task_seed.enhanced_title or task_seed.confirmed_title or f"第 {chapter_index} 章"
    glossary_terms = [
        item.term
        for item in document_backbone.canonical_glossary
        if chapter_index in item.target_chapters and item.term
    ]
    claim_targets = [
        item.claim_text
        for item in document_backbone.canonical_claim_pool
        if item.target_chapter == chapter_index and item.claim_text
    ]
    confusion_targets = [
        item.topic or item.contrast
        for item in document_backbone.confusion_map
        if chapter_index in item.target_chapters and (item.topic or item.contrast)
    ]
    core_targets = clean_string_list(
        [*task_seed.required_elements, *glossary_terms, *claim_targets, title],
        limit=6,
    )
    if not core_targets:
        core_targets = [title]
    examples = core_targets[: min(3, len(core_targets))]
    pitfalls = clean_string_list(confusion_targets, limit=2)
    teaching_outline = clean_string_list(
        [
            f"建立{core_targets[0]}的概念边界和使用条件",
            f"通过例题或案例串联{'、'.join(examples)}",
            (
                f"辨析{'、'.join(pitfalls)}并总结迁移检查点"
                if pitfalls
                else f"总结{core_targets[0]}的易错边界和迁移检查点"
            ),
        ],
        limit=3,
    )
    role_targets: dict[str, list[str]] = {"concept": core_targets[:4]}
    if claim_targets:
        role_targets["principle"] = clean_string_list(claim_targets, limit=2)
    if pitfalls:
        role_targets["misconception"] = pitfalls
    return ChapterExecutionBrief(
        chapter_index=chapter_index,
        teaching_outline=teaching_outline,
        content_role_targets=role_targets,
        example_coverage_plan=[
            {
                "target": target,
                "example_type": "worked_example_or_case",
                "purpose": f"用可执行示例检查对{target}的理解和迁移",
                "min_examples": 1,
            }
            for target in examples
        ],
        chapter_end_practice_plan=[
            {
                "target": target,
                "example_type": "chapter_end_practice",
                "purpose": f"检查{target}的独立应用能力",
                "min_examples": 1,
            }
            for target in examples[:2]
        ],
        concept_targets=core_targets[:2],
        definition_targets=glossary_terms[:2],
        example_targets=examples[:2],
        pitfall_targets=pitfalls,
        retrieval_queries=clean_string_list(
            [*task_seed.retrieval_queries, title, *core_targets],
            limit=2,
        ),
        fallback_used=False,
    )


def build_chapter_execution_briefs_node(*, context: WorkflowContext):
    """构建章节执行 brief 节点。"""

    async def build_chapter_execution_briefs_node_impl(state: DocGenState) -> dict:
        started_at = perf_counter()
        task_seeds = [
            ChapterGenerationTaskSeed.model_validate(item)
            for item in sorted(
                list(state.get("chapter_task_seeds") or []),
                key=lambda raw: int((raw or {}).get("chapter_index", 0) or 0),
            )
        ]
        if not task_seeds:
            return {"error": "缺少可生成执行 brief 的章节 seed。"}
        document_backbone = DocumentBackbone.model_validate(state.get("document_backbone") or {})
        chapter_briefs: list[dict] = []
        for task_seed in task_seeds:
            brief = _build_deterministic_brief(
                task_seed,
                document_backbone=document_backbone,
            )
            append_knowledge_build_recent_event(
                state["course_id"],
                requested_at=state["requested_at"],
                build_group_id=state.get("build_group_id") or None,
                event={
                    "stage": "chapter_execution_brief_ready",
                    "chapter_index": task_seed.chapter_index,
                    "summary": f"第 {task_seed.chapter_index} 章执行 brief 已生成。",
                    "detail": "",
                    "created_at": utcnow(),
                },
            )
            chapter_briefs.append(brief.model_dump(mode="json"))
        chapter_briefs.sort(key=lambda item: int(item.get("chapter_index", 0) or 0))
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        await publish_docgen_progress(
            context,
            state=state,
            stage="chapter_execution_briefs_ready",
            payload={
                "chapter_count": len(chapter_briefs),
                "fallback_count": 0,
                "kg_prefetch_started": False,
                "brief_mode": "compiled_from_confirmed_contract",
            },
        )
        return {
            "chapter_execution_briefs": chapter_briefs,
            "kg_prefetch_status": "deferred_until_reviewed_chapters",
            "kg_prefetch_ready": False,
            "chapter_prepare_ms": elapsed_ms,
            "llm_calls_total": 0,
        }

    return build_chapter_execution_briefs_node_impl


__all__ = ["build_chapter_execution_briefs_node"]
