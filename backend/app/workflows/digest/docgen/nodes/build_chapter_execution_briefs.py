"""Build chapter execution briefs in parallel after backbone construction."""

from __future__ import annotations

from time import perf_counter
from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import append_knowledge_build_recent_event
from app.shared.infra.settings import get_settings
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
    """Compile transport fields without inventing chapter semantics locally.

    Planner already produced the user-confirmed objective, required elements and
    writing instructions.  The Writer prompt owns pedagogical expansion; this
    node must not replace the removed LLM brief with a universal lesson template
    or guess knowledge-unit roles.
    """

    del document_backbone
    return ChapterExecutionBrief(
        chapter_index=task_seed.chapter_index,
        retrieval_queries=clean_string_list(
            task_seed.retrieval_queries,
            limit=get_settings().docgen.max_retrieval_queries_per_chapter,
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
            "kg_prefetch_status": "deferred_until_enhanced_chapters",
            "kg_prefetch_ready": False,
            "chapter_prepare_ms": elapsed_ms,
            "llm_calls_total": 0,
        }

    return build_chapter_execution_briefs_node_impl


__all__ = ["build_chapter_execution_briefs_node"]
