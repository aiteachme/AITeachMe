"""Draft one chapter of the knowledge docs."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.services.upload_support import build_docgen_intermediate_latest_dir
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.writer_service import (
    build_global_outline_summary,
    write_chapter,
)
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_draft_chapter_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """Build the fan-out chapter draft node."""

    async def draft_chapter_node(state: dict) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="draft_chapter")

        chapter = state["chapter"]
        outline_tree = state.get("outline_tree", {})
        total_chapters = state.get("total_chapters", 1)
        user_prompt = state.get("user_prompt")
        prev_summary = state.get("prev_summary", "")
        next_preview = state.get("next_preview", "")
        subject = state.get("subject", "")

        chapter_index = chapter["chapter_index"]
        chapter_title = chapter.get("title", f"第{chapter_index}章")
        source_contents = chapter.get("source_contents", [])
        section_titles = list(chapter.get("section_titles", []))
        formula_refs = list(chapter.get("formula_refs", []))
        source_brief = str(chapter.get("source_brief", ""))
        source_text = "\n\n---\n\n".join(source_contents) if source_contents else "（无原始素材）"

        node_logger.info(
            "docgen_drafting_chapter",
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            total_chapters=total_chapters,
            source_chunk_count=len(source_contents),
            section_count=len(section_titles),
        )

        global_outline_text = build_global_outline_summary(outline_tree)
        async with strategy.chapter_semaphore:
            markdown = await write_chapter(
                chapter_title=chapter_title,
                chapter_index=chapter_index,
                total_chapters=total_chapters,
                global_outline_text=global_outline_text,
                section_titles=section_titles,
                user_prompt=user_prompt,
                prev_summary=prev_summary,
                next_preview=next_preview,
                source_brief=source_brief,
                formula_refs=formula_refs,
                source_content=source_text,
            )

        if subject:
            intermediate_dir = build_docgen_intermediate_latest_dir(subject)
            intermediate_dir.mkdir(parents=True, exist_ok=True)
            safe_title = chapter_title.replace("/", "_").replace("\\", "_")[:30]
            (intermediate_dir / f"draft_{chapter_index:02d}_{safe_title}.md").write_text(
                markdown,
                encoding="utf-8",
            )

        draft_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_drafting_chapter_completed",
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            chars=len(markdown),
            draft_ms=draft_ms,
        )
        return {
            "chapter_drafts": [
                {
                    "chapter_index": chapter_index,
                    "title": chapter_title,
                    "markdown": markdown,
                    "source_contents": source_contents,
                    "section_titles": section_titles,
                    "formula_refs": formula_refs,
                    "source_brief": source_brief,
                    "prev_summary": prev_summary,
                    "next_preview": next_preview,
                }
            ],
            "draft_ms": draft_ms,
            "llm_calls_total": 1,
        }

    return draft_chapter_node
