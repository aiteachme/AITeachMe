"""Build the global outline and chapter assignments."""

from __future__ import annotations

import json
from time import perf_counter

import structlog

from app.services.upload_support import build_docgen_intermediate_latest_dir
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.outline_service import (
    build_chapter_assignments,
    build_fallback_outline_tree,
    ensure_multi_chapter_outline,
    generate_global_outline,
)
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_outline_reduce_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """Build the outline reduce node."""

    async def outline_reduce_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        node_logger = context.get_logger().bind(node="outline_reduce")
        clean_chunks = state.get("clean_chunks", [])
        local_outlines = state.get("local_outlines", [])
        user_prompt = state.get("user_prompt")
        subject = state["subject"]
        node_logger.info(
            "docgen_planning_outline",
            clean_chunk_count=len(clean_chunks),
            local_outline_count=len(local_outlines),
        )

        local_text = "\n".join(
            (
                f"文本块 {item['chunk_index']}（来源：{item['source_filename']}）\n"
                f"标题候选：{', '.join(item['titles']) or '（无）'}\n"
                f"内容预览：{item.get('preview', '（无预览）')}"
            )
            for item in local_outlines
        )

        outline_plan = strategy.plan_outline(
            chunk_count=len(clean_chunks),
            local_outlines=local_outlines,
            user_prompt=user_prompt,
        )

        node_logger.info(
            "docgen_planning_outline_llm",
            mode=outline_plan.mode,
            reason=outline_plan.reason,
        )
        try:
            outline_tree = await generate_global_outline(
                chunk_count=len(clean_chunks),
                local_outlines_text=local_text,
                user_prompt=user_prompt,
            )
            llm_calls_total = 1
        except Exception:
            node_logger.warning(
                "docgen_planning_outline_fallback",
                reason="llm_outline_failed",
            )
            outline_tree = build_fallback_outline_tree(clean_chunks, local_outlines)
            llm_calls_total = 0

        raw_chapter_count = len(outline_tree.get("chapters", []))
        outline_tree = ensure_multi_chapter_outline(outline_tree, clean_chunks, local_outlines)
        normalized_chapter_count = len(outline_tree.get("chapters", []))
        if normalized_chapter_count > raw_chapter_count:
            node_logger.info(
                "docgen_planning_outline_rebalanced",
                previous_chapter_count=raw_chapter_count,
                chapter_count=normalized_chapter_count,
                reason="prevent_single_chapter_publish",
            )

        chapter_assignments = build_chapter_assignments(outline_tree, clean_chunks)

        out_dir = build_docgen_intermediate_latest_dir(subject)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "outline_tree.json").write_text(
            json.dumps(outline_tree, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (out_dir / "chapter_assignments.json").write_text(
            json.dumps(
                [
                    {
                        "chapter_index": assignment["chapter_index"],
                        "title": assignment["title"],
                        "section_count": len(assignment["sections"]),
                        "chars": sum(len(content) for content in assignment["source_contents"]),
                    }
                    for assignment in chapter_assignments
                ],
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        outline_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info(
            "docgen_planning_outline_completed",
            chapter_count=len(chapter_assignments),
            outline_ms=outline_ms,
            llm_calls_total=llm_calls_total,
        )
        return {
            "outline_tree": outline_tree,
            "chapter_assignments": chapter_assignments,
            "outline_ms": outline_ms,
            "llm_calls_total": llm_calls_total,
        }

    return outline_reduce_node
