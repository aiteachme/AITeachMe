"""Fan-Out 子节点：对单章草稿进行质检。"""

from __future__ import annotations

from time import perf_counter

import structlog

from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.writer_service import (
    audit_chapter,
    normalize_chapter_markdown,
    review_chapter,
    revise_chapter_targeted,
    should_retry_review,
)
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_review_chapter_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """构建单章质检 Fan-Out 子节点。

    检查草稿质量，不通过时仅对硬失败做定向修订。
    返回 ``chapter_reviews`` 列表（单元素），由 operator.add 汇聚。
    """

    async def review_chapter_node(state: dict) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="review_chapter")

        draft = state["draft"]
        user_prompt = state.get("user_prompt")

        ch_index = draft["chapter_index"]
        ch_title = draft["title"]
        markdown = draft["markdown"]
        source_contents = draft.get("source_contents", [])
        section_titles = list(draft.get("section_titles", []))
        formula_refs = list(draft.get("formula_refs", []))
        source_summary = "\n".join(sc[:200] for sc in source_contents[:3])
        total_chapters = int(state.get("total_chapters", 1))
        llm_calls_total = 0

        node_logger.info(
            "review_start",
            chapter_index=ch_index,
            max_parallel_chapters=strategy.max_parallel_chapters,
            review_retry_mode=strategy.review_retry_mode,
        )

        review_plan = strategy.plan_review(
            total_chapters=total_chapters,
            source_chunk_count=len(source_contents),
            markdown=markdown,
            user_prompt=user_prompt,
        )

        normalized_markdown = normalize_chapter_markdown(
            markdown=markdown,
            chapter_title=ch_title,
            section_titles=section_titles,
            formula_refs=formula_refs,
        )
        review_result = audit_chapter(
            markdown=normalized_markdown,
            chapter_title=ch_title,
            section_titles=section_titles,
            formula_refs=formula_refs,
        )

        if not review_result.get("needs_llm") or review_plan.mode == "rule_based_only":
            node_logger.info(
                "review_fast_path_used",
                chapter_index=ch_index,
                reason=review_plan.reason,
                passed=review_result.get("passed", True),
                issues=review_result.get("issues", []),
            )
        else:
            async with strategy.chapter_semaphore:
                llm_review = await review_chapter(normalized_markdown, source_summary, user_prompt=user_prompt)
            llm_calls_total += 1
            merged_issues = list(dict.fromkeys([
                *[str(item) for item in review_result.get("issues", [])],
                *[str(item) for item in llm_review.get("issues", [])],
            ]))
            merged_suggestions = list(dict.fromkeys([
                *[str(item) for item in review_result.get("suggestions", [])],
                *[str(item) for item in llm_review.get("suggestions", [])],
            ]))
            review_result = {
                "passed": bool(review_result.get("passed", True) and llm_review.get("passed", True)),
                "issues": merged_issues,
                "suggestions": merged_suggestions,
                "needs_llm": True,
            }

        final_markdown = normalized_markdown
        if strategy.review_retry_mode == "targeted" and should_retry_review(
            markdown=final_markdown,
            review_result=review_result,
        ):
            issues = review_result.get("issues", [])
            node_logger.warning(
                "review_issues_detected", chapter_index=ch_index,
                issues=issues,
            )
            try:
                async with strategy.chapter_semaphore:
                    final_markdown = await revise_chapter_targeted(
                        final_markdown,
                        issues=list(issues),
                        source_summary=source_summary,
                        user_prompt=user_prompt,
                    )
                llm_calls_total += 1
                final_markdown = normalize_chapter_markdown(
                    markdown=final_markdown,
                    chapter_title=ch_title,
                    section_titles=section_titles,
                    formula_refs=formula_refs,
                )
                review_result = audit_chapter(
                    markdown=final_markdown,
                    chapter_title=ch_title,
                    section_titles=section_titles,
                    formula_refs=formula_refs,
                )
                node_logger.info("review_rewrite_done", chapter_index=ch_index)
            except Exception as exc:
                node_logger.error("review_rewrite_failed", error=str(exc))

        review_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "review_done",
            chapter_index=ch_index,
            passed=review_result.get("passed", True),
            review_ms=review_ms,
            llm_calls_total=llm_calls_total,
        )
        return {
            "chapter_reviews": [{
                "chapter_index": ch_index,
                "title": ch_title,
                "markdown": final_markdown,
                "review": review_result,
                "source_contents": source_contents,
                "section_titles": section_titles,
                "formula_refs": formula_refs,
            }],
            "review_ms": review_ms,
            "llm_calls_total": llm_calls_total,
        }

    return review_chapter_node
