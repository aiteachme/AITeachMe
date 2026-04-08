"""Inject examine node for the DocGen lane."""

from __future__ import annotations

from copy import deepcopy

from app.shared.infra.tools.builtin.markdown_processing import prepend_table_of_contents
from app.utils.docgen_store import append_knowledge_build_recent_event, update_knowledge_build_status
from app.utils.time import utcnow
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import build_examine_markdown, publish_docgen_progress
from app.workflows.digest.docgen.publish import build_merged_markdown
from app.workflows.digest.docgen.state import DocGenState


def build_inject_examine_node(*, context: WorkflowContext):
    async def inject_examine_node(state: DocGenState) -> dict:
        chapter_metadatas = sorted(
            deepcopy(list(state.get("chapter_metadatas", []))),
            key=lambda item: item.get("chapter_index", 0),
        )
        if not chapter_metadatas:
            return {"error": "当前没有可用于注入练习内容的章节。"}

        question_titles = [
            str(chapter.get("title") or "").strip()
            for chapter in chapter_metadatas[:3]
            if str(chapter.get("title") or "").strip()
        ]
        exam_questions = [
            {
                "question_index": index,
                "type": "short_answer",
                "question": f"请解释《{title}》的核心思想，并把它和一个具体例子联系起来。",
            }
            for index, title in enumerate(question_titles, start=1)
        ]
        practice_markdown = build_examine_markdown(question_titles)
        next_index = max(int(chapter.get("chapter_index", 0) or 0) for chapter in chapter_metadatas) + 1
        chapter_metadatas.append(
            {
                "chapter_index": next_index,
                "title": "练习与自检",
                "markdown": practice_markdown,
                "summary": "本章之后的练习提示与自检问题。",
                "tags": ["practice", "self_check"],
                "digest_mode": state.get("digest_mode") or "",
                "source_file_ids": sorted(
                    {
                        int(file_id)
                        for chapter in chapter_metadatas
                        for file_id in chapter.get("source_file_ids", [])
                    }
                ),
                "sources": [],
                "source_details": [],
            }
        )
        merged_markdown = prepend_table_of_contents(
            build_merged_markdown(
                chapter_metadatas,
                document_context=dict(state.get("document_context") or {}),
            ),
            min_level=2,
            max_level=4,
        )
        update_knowledge_build_status(
            state["subject"],
            requested_at=state["requested_at"],
            status="running",
            stage="publishing",
            digest_mode=state.get("digest_mode") or None,
            staged_chapter_count=len(chapter_metadatas),
            current_stage_description="文档组装完成，开始发布知识文档。",
            draft_available=bool(merged_markdown.strip()),
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "examine_injected",
                "summary": f"练习与自检内容已注入，新增 {len(exam_questions)} 道自检题。",
                "created_at": utcnow(),
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="examine_injected",
            payload={
                "question_count": len(exam_questions),
                "chapter_count": len(chapter_metadatas),
            },
        )
        return {
            "chapter_metadatas": chapter_metadatas,
            "exam_questions": exam_questions,
            "merged_markdown": merged_markdown,
            "enriched_markdown": merged_markdown,
        }

    return inject_examine_node


__all__ = ["build_inject_examine_node"]
