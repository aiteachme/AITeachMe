"""阶段三：多智能体并发撰写节点。

为每个章节组装上下文数据包，并发调用 Writer Agent 生成教学文档。
"""

from __future__ import annotations

import asyncio
import json

import structlog

from app.core.database import managed_session
from app.core.llm import acompletion
from app.core.model_router import TaskType
from app.repositories.knowledge import docgen_repo
from app.services.upload_support import build_docgen_intermediate_dir
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docs.state import DocGenState
from app.workflows.digest.prompts.docgen_prompts import WRITER_PROMPT

logger = structlog.get_logger()

# 并发写作的最大并行数（受 LLM 并发限制保护）
_MAX_WRITER_CONCURRENCY = 5


def _build_global_outline_summary(outline_tree: dict) -> str:
    """将目录树转为可读的大纲文本。"""

    lines: list[str] = []
    for chapter in outline_tree.get("chapters", []):
        ch_idx = chapter.get("chapter_index", "?")
        ch_title = chapter.get("title", "")
        lines.append(f"第{ch_idx}章 {ch_title}")
        for section in chapter.get("sections", []):
            lines.append(f"  - {section.get('title', '')}")
    return "\n".join(lines)


async def _write_chapter(
    *,
    chapter: dict,
    chapter_index: int,
    total_chapters: int,
    global_outline_text: str,
    prev_summary: str,
    next_preview: str,
    node_logger,
) -> dict:
    """调用 Writer Agent 撰写单个章节。"""

    title = chapter.get("title", f"第{chapter_index}章")
    source_contents = chapter.get("source_contents", [])
    source_text = "\n\n---\n\n".join(source_contents) if source_contents else "（无原始素材）"

    # 截取合理长度（避免超出 token 限制）
    max_source_chars = 15000
    if len(source_text) > max_source_chars:
        source_text = source_text[:max_source_chars] + "\n\n（原始素材过长，已截取前半部分）"

    prompt = WRITER_PROMPT.format(
        global_outline=global_outline_text,
        chapter_title=title,
        chapter_index=chapter_index,
        total_chapters=total_chapters,
        prev_summary=prev_summary or "（本章为第一章，无上一节内容）",
        source_content=source_text,
        next_preview=next_preview or "（本章为最后一章，无后续内容）",
    )

    try:
        markdown = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN,
        )
        node_logger.info("draft_chapter_done", chapter_index=chapter_index, chars=len(markdown))
        return {
            "chapter_index": chapter_index,
            "title": title,
            "markdown": markdown.strip(),
        }
    except Exception as exc:
        node_logger.error("draft_chapter_failed", chapter_index=chapter_index, error=str(exc))
        # 兜底：使用原始素材构建最小文档
        fallback_md = f"# {title}\n\n> 📌 本章概要：本章节自动生成失败，以下为原始素材内容。\n\n{source_text}"
        return {
            "chapter_index": chapter_index,
            "title": title,
            "markdown": fallback_md,
        }


def build_draft_node(*, context: WorkflowContext):
    """构建多智能体并发撰写节点。"""

    async def draft_node(state: DocGenState) -> dict:
        node_logger = context.get_logger().bind(node="draft")
        node_logger.info("draft_started")

        subject = state["subject"]
        job_id = state["job_id"]
        outline_tree = state.get("outline_tree", {})
        chapter_assignments = state.get("chapter_assignments", [])

        with managed_session() as session:
            docgen_repo.update_docgen_job(
                session, job_id, current_step="drafting", progress=45,
            )

        if not chapter_assignments:
            return {"error": "没有章节分配数据，无法撰写。"}

        total_chapters = len(chapter_assignments)
        global_outline_text = _build_global_outline_summary(outline_tree)

        # 并发撰写
        semaphore = asyncio.Semaphore(_MAX_WRITER_CONCURRENCY)

        async def _write_with_semaphore(idx: int, chapter: dict) -> dict:
            async with semaphore:
                # 构建上下文
                prev_summary = ""
                if idx > 0:
                    prev_chapter = chapter_assignments[idx - 1]
                    prev_summary = f"上一章「{prev_chapter['title']}」主要讨论了相关主题。"

                next_preview = ""
                if idx < total_chapters - 1:
                    next_chapter = chapter_assignments[idx + 1]
                    next_preview = f"下一章「{next_chapter['title']}」将继续讨论后续主题。"

                result = await _write_chapter(
                    chapter=chapter,
                    chapter_index=chapter["chapter_index"],
                    total_chapters=total_chapters,
                    global_outline_text=global_outline_text,
                    prev_summary=prev_summary,
                    next_preview=next_preview,
                    node_logger=node_logger,
                )

                # 更新进度
                with managed_session() as session:
                    completed = idx + 1
                    progress = 45 + int(35 * completed / total_chapters)
                    docgen_repo.update_docgen_job(
                        session, job_id,
                        progress=progress,
                        completed_chapters=completed,
                    )

                return result

        tasks = [
            asyncio.create_task(_write_with_semaphore(idx, chapter))
            for idx, chapter in enumerate(chapter_assignments)
        ]
        chapter_drafts = await asyncio.gather(*tasks)

        # 按 chapter_index 排序
        sorted_drafts = sorted(chapter_drafts, key=lambda d: d["chapter_index"])

        # 保存中间产物——每章草稿单独写入磁盘
        intermediate_dir = build_docgen_intermediate_dir(subject)
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        for draft in sorted_drafts:
            safe_title = draft["title"].replace("/", "_").replace("\\", "_")[:30]
            draft_path = intermediate_dir / f"draft_{draft['chapter_index']:02d}_{safe_title}.md"
            draft_path.write_text(draft["markdown"], encoding="utf-8")

        node_logger.info("draft_completed", chapter_count=len(sorted_drafts))
        return {"chapter_drafts": list(sorted_drafts)}

    return draft_node
