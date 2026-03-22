"""Fan-Out 子节点：对单章草稿进行质检。"""

from __future__ import annotations

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.writer_service import (
    review_chapter,
    write_chapter,
    build_global_outline_summary,
)

logger = structlog.get_logger()


def build_review_chapter_node(*, context: WorkflowContext):
    """构建单章质检 Fan-Out 子节点。

    检查草稿质量，不通过则尝试重写一次。
    返回 ``chapter_reviews`` 列表（单元素），由 operator.add 汇聚。
    """

    async def review_chapter_node(state: dict) -> dict:
        node_logger = context.get_logger().bind(node="review_chapter")

        draft = state["draft"]
        outline_tree = state.get("outline_tree", {})
        total_chapters = state.get("total_chapters", 1)
        user_prompt = state.get("user_prompt")

        ch_index = draft["chapter_index"]
        ch_title = draft["title"]
        markdown = draft["markdown"]
        source_contents = draft.get("source_contents", [])
        source_summary = "\n".join(sc[:200] for sc in source_contents[:3])

        node_logger.info("review_start", chapter_index=ch_index)

        review_result = await review_chapter(markdown, source_summary, user_prompt=user_prompt)

        final_markdown = markdown
        if not review_result.get("passed", True):
            issues = review_result.get("issues", [])
            node_logger.warning(
                "review_failed", chapter_index=ch_index,
                issues=issues,
            )
            # 尝试重写一次
            try:
                source_text = "\n\n---\n\n".join(source_contents) if source_contents else ""
                global_outline_text = build_global_outline_summary(outline_tree)
                rewritten = await write_chapter(
                    chapter_title=ch_title,
                    chapter_index=ch_index,
                    total_chapters=total_chapters,
                    global_outline_text=global_outline_text,
                    user_prompt=user_prompt,
                    prev_summary="",
                    next_preview="",
                    source_content=source_text,
                )
                final_markdown = rewritten
                node_logger.info("review_rewrite_done", chapter_index=ch_index)
            except Exception as exc:
                node_logger.error("review_rewrite_failed", error=str(exc))
                # 保持原稿

        node_logger.info("review_done", chapter_index=ch_index, passed=review_result.get("passed", True))
        return {
            "chapter_reviews": [{
                "chapter_index": ch_index,
                "title": ch_title,
                "markdown": final_markdown,
                "review": review_result,
                "source_contents": source_contents,
            }],
        }

    return review_chapter_node
