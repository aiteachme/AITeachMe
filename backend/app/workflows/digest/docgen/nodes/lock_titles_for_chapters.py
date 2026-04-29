"""Lock final chapter titles in parallel before backbone seeding."""

from __future__ import annotations

import asyncio
from time import perf_counter

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import (
    append_knowledge_build_recent_event,
    upsert_knowledge_build_chapter_progress,
)
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.models import DocGenContext
from app.workflows.digest.docgen.lib.title_lock import lock_title_for_chapter
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress
from app.workflows.digest.docgen.state import DocGenState


def build_lock_titles_for_chapters_node(*, context: WorkflowContext):
    """构建章节标题锁定节点。"""

    async def lock_titles_for_chapters_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        chapters = sorted(
            list(state.get("chapter_assignments") or []),
            key=lambda item: int(item.get("chapter_index", 0) or 0),
        )
        if not chapters:
            return {"error": "缺少可锁定标题的章节合同。"}
        docgen_context = DocGenContext.model_validate(state.get("docgen_context") or {})

        async def _lock_one(chapter: dict) -> dict:
            locked = await lock_title_for_chapter(
                course_name=docgen_context.course_name,
                digest_mode=docgen_context.digest_mode,
                user_prompt=docgen_context.user_prompt,
                plan_summary=docgen_context.plan_summary,
                chapter=chapter,
                docgen_history_brief=docgen_context.docgen_history_brief,
                extra_metadata={
                    "build_session_id": state.get("build_session_id") or "",
                    "planner_session_id": state.get("planner_session_id") or "",
                    "confirmed_plan_id": state.get("confirmed_plan_id") or "",
                    "chapter_index": int(chapter.get("chapter_index", 0) or 0),
                },
            )
            append_knowledge_build_recent_event(
                state["course_id"],
                requested_at=state["requested_at"],
                event={
                    "stage": "chapter_title_locked",
                    "chapter_index": locked.chapter_index,
                    "summary": f"第 {locked.chapter_index} 章标题已锁定为《{locked.enhanced_title}》。",
                    "created_at": utcnow(),
                },
            )
            upsert_knowledge_build_chapter_progress(
                state["course_id"],
                requested_at=state["requested_at"],
                chapter_progress={
                    "chapter_index": locked.chapter_index,
                    "title": locked.enhanced_title,
                    "status": "planned",
                },
            )
            return locked.model_dump(mode="json")

        locked_titles = list(await asyncio.gather(*(_lock_one(chapter) for chapter in chapters)))
        locked_titles.sort(key=lambda item: int(item.get("chapter_index", 0) or 0))
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        await publish_docgen_progress(
            context,
            state=state,
            stage="chapter_titles_locked",
            payload={
                "chapter_count": len(locked_titles),
                "fallback_count": sum(1 for item in locked_titles if bool(item.get("fallback_used", False))),
            },
        )
        return {
            "locked_titles": locked_titles,
            "title_lock_ms": elapsed_ms,
            "llm_calls_total": len(locked_titles),
        }

    return lock_titles_for_chapters_node


__all__ = ["build_lock_titles_for_chapters_node"]
