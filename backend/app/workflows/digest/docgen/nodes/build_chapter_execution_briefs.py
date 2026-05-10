"""Build chapter execution briefs in parallel after backbone construction."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.llm_support import run_llm_tasks
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.chapter_execution_brief import build_chapter_execution_brief
from app.workflows.digest.docgen.lib.models import ChapterGenerationTaskSeed, DocGenContext, DocumentBackbone
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


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
        docgen_context = DocGenContext.model_validate(state.get("docgen_context") or {})
        document_backbone = DocumentBackbone.model_validate(state.get("document_backbone") or {})
        intent_core = dict(state.get("intent_core") or {})

        async def _build_one(task_seed: ChapterGenerationTaskSeed) -> dict:
            glossary_terms = [
                item.term
                for item in document_backbone.canonical_glossary
                if task_seed.chapter_index in item.target_chapters and item.term
            ][:4]
            claim_targets = [
                item.claim_text
                for item in document_backbone.canonical_claim_pool
                if item.target_chapter == task_seed.chapter_index and item.claim_text
            ][:4]
            confusion_targets = [
                item.topic or item.contrast
                for item in document_backbone.confusion_map
                if task_seed.chapter_index in item.target_chapters and (item.topic or item.contrast)
            ][:3]
            brief = await build_chapter_execution_brief(
                course_name=docgen_context.course_name,
                digest_mode=docgen_context.digest_mode,
                chapter={
                    "chapter_index": task_seed.chapter_index,
                    "title": task_seed.confirmed_title,
                    "resolved_title": task_seed.enhanced_title,
                    "objective": task_seed.chapter_goal,
                    "required_elements": task_seed.required_elements,
                },
                locked_title=task_seed.enhanced_title or task_seed.confirmed_title,
                intent_core=intent_core,
                glossary_terms=glossary_terms,
                claim_targets=claim_targets,
                confusion_targets=confusion_targets,
                extra_metadata={
                    "build_session_id": state.get("build_session_id") or "",
                    "planner_session_id": state.get("planner_session_id") or "",
                    "confirmed_plan_id": state.get("confirmed_plan_id") or "",
                    "chapter_index": task_seed.chapter_index,
                },
            )
            append_knowledge_build_recent_event(
                state["course_id"],
                requested_at=state["requested_at"],
                event={
                    "stage": "chapter_execution_brief_ready",
                    "chapter_index": task_seed.chapter_index,
                    "summary": f"第 {task_seed.chapter_index} 章执行 brief 已生成。",
                    "created_at": utcnow(),
                },
            )
            return brief.model_dump(mode="json")

        chapter_briefs = await run_llm_tasks(
            task_seeds,
            _build_one,
        )
        chapter_briefs.sort(key=lambda item: int(item.get("chapter_index", 0) or 0))
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        await publish_docgen_progress(
            context,
            state=state,
            stage="chapter_execution_briefs_ready",
            payload={
                "chapter_count": len(chapter_briefs),
                "fallback_count": sum(1 for item in chapter_briefs if bool(item.get("fallback_used", False))),
            },
        )
        return {
            "chapter_execution_briefs": chapter_briefs,
            "chapter_prepare_ms": elapsed_ms,
            "llm_calls_total": len(chapter_briefs),
        }

    return build_chapter_execution_briefs_node_impl


__all__ = ["build_chapter_execution_briefs_node"]
