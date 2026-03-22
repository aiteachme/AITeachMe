"""Fan-Out 子节点：撰写单个章节（由 Send 分发）。

Reads DB: none.
Writes DB: none.
Writes FS: writes chapter draft markdown into ``docgen_intermediate/``.
Idempotency: reruns overwrite the same draft file for the same chapter index.
"""

from __future__ import annotations

import asyncio
from time import perf_counter

import structlog

from app.services.upload_support import build_docgen_intermediate_dir
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.services.writer_service import (
    build_global_outline_summary,
    write_chapter,
)
from app.workflows.digest.docs.strategy import DocGenExecutionStrategy

logger = structlog.get_logger()


def build_draft_chapter_node(*, context: WorkflowContext, strategy: DocGenExecutionStrategy):
    """构建单章撰写 Fan-Out 子节点。

    接收 Send 分发的 payload，包含单章所需全部信息。
    返回 ``chapter_drafts`` 列表（单元素），由 operator.add 汇聚。
    """

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

        ch_index = chapter["chapter_index"]
        ch_title = chapter.get("title", f"第{ch_index}章")
        source_contents = chapter.get("source_contents", [])
        section_titles = list(chapter.get("section_titles", []))
        formula_refs = list(chapter.get("formula_refs", []))
        source_brief = str(chapter.get("source_brief", ""))
        source_text = "\n\n---\n\n".join(source_contents) if source_contents else "（无原始素材）"

        node_logger.info(
            "draft_chapter_start",
            chapter_index=ch_index,
            total_chapters=total_chapters,
            source_chunk_count=len(source_contents),
            section_count=len(section_titles),
            max_parallel_chapters=strategy.max_parallel_chapters,
        )

        global_outline_text = build_global_outline_summary(outline_tree)
        llm_calls_total = 0

        async with strategy.chapter_semaphore:
            markdown = await write_chapter(
                chapter_title=ch_title,
                chapter_index=ch_index,
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
        llm_calls_total = 1

        # 保存草稿中间产物
        if subject:
            out_dir = build_docgen_intermediate_dir(subject)
            out_dir.mkdir(parents=True, exist_ok=True)
            safe_title = ch_title.replace("/", "_").replace("\\", "_")[:30]
            (out_dir / f"draft_{ch_index:02d}_{safe_title}.md").write_text(
                markdown, encoding="utf-8",
            )

        draft_ms = int((perf_counter() - started_at) * 1000)
        node_logger.info("draft_chapter_done", chapter_index=ch_index, chars=len(markdown), draft_ms=draft_ms)
        return {
            "chapter_drafts": [{
                "chapter_index": ch_index,
                "title": ch_title,
                "markdown": markdown,
                "source_contents": source_contents,
                "section_titles": section_titles,
                "formula_refs": formula_refs,
            }],
            "draft_ms": draft_ms,
            "llm_calls_total": llm_calls_total,
        }

    return draft_chapter_node
