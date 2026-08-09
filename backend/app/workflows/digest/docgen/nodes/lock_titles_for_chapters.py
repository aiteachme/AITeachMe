"""Lock final chapter titles in parallel before backbone seeding."""

from __future__ import annotations

from time import perf_counter

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.knowledge.build_store import (
    append_knowledge_build_recent_event,
    upsert_knowledge_build_chapter_progress,
)
from app.utils.time import utcnow
from app.workflows.digest.docgen.lib.title_lock import fallback_locked_title
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
            return {"error": "缺少可锁定标题的学习大纲。"}
        async def _lock_one(chapter: dict) -> dict:
            locked = fallback_locked_title(chapter).model_copy(
                update={"fallback_used": False},
            )
            append_knowledge_build_recent_event(
                state["course_id"],
                requested_at=state["requested_at"],
                build_group_id=state.get("build_group_id") or None,
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
                build_group_id=state.get("build_group_id") or None,
                chapter_progress={
                    "chapter_index": locked.chapter_index,
                    "title": locked.enhanced_title,
                    "status": "planned",
                },
            )
            return locked.model_dump(mode="json")

        locked_titles = [await _lock_one(chapter) for chapter in chapters]
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
            "llm_calls_total": 0,
        }

    return lock_titles_for_chapters_node


__all__ = ["build_lock_titles_for_chapters_node"]
