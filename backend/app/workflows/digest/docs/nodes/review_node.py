"""Review one drafted chapter of the knowledge docs."""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.writer_service import (
    build_global_outline_summary,
    review_chapter,
    write_chapter,
)
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_review_chapter_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """Build the fan-out chapter review node."""

    async def review_chapter_node(state: dict) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="review_chapter")

        draft = state["draft"]
        outline_tree = state.get("outline_tree", {})
        total_chapters = int(state.get("total_chapters", 1))
        user_prompt = state.get("user_prompt")

        chapter_index = draft["chapter_index"]
        chapter_title = draft["title"]
        markdown = draft["markdown"]
        source_contents = draft.get("source_contents", [])
        section_titles = list(draft.get("section_titles", []))
        formula_refs = list(draft.get("formula_refs", []))
        source_brief = str(draft.get("source_brief", ""))
        prev_summary = str(draft.get("prev_summary", ""))
        next_preview = str(draft.get("next_preview", ""))
        source_summary = "\n".join(content[:300] for content in source_contents[:3])

        node_logger.info(
            "docgen_reviewing_chapter",
            chapter_index=chapter_index,
            chapter_title=chapter_title,
        )

        async with strategy.chapter_semaphore:
            review_result = await review_chapter(markdown, source_summary, user_prompt=user_prompt)
        llm_calls_total = 1
        final_markdown = markdown

        if not review_result.get("passed", True):
            node_logger.warning(
                "docgen_reviewing_chapter_retry",
                chapter_index=chapter_index,
                chapter_title=chapter_title,
                issues=review_result.get("issues", []),
            )
            global_outline_text = build_global_outline_summary(outline_tree)
            source_text = "\n\n---\n\n".join(source_contents) if source_contents else "（无原始素材）"
            async with strategy.chapter_semaphore:
                final_markdown = await write_chapter(
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
                review_result = await review_chapter(final_markdown, source_summary, user_prompt=user_prompt)
            llm_calls_total += 2

        review_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_reviewing_chapter_completed",
            chapter_index=chapter_index,
            chapter_title=chapter_title,
            passed=review_result.get("passed", True),
            review_ms=review_ms,
        )
        return {
            "chapter_reviews": [
                {
                    "chapter_index": chapter_index,
                    "title": chapter_title,
                    "markdown": final_markdown,
                    "review": review_result,
                    "source_contents": source_contents,
                    "section_titles": section_titles,
                    "formula_refs": formula_refs,
                }
            ],
            "review_ms": review_ms,
            "llm_calls_total": llm_calls_total,
        }

    return review_chapter_node
