"""撰写 & 质检阶段纯函数服务。"""

from __future__ import annotations

import json

import structlog

from app.core.llm import acompletion
from app.core.model_router import TaskType
from app.workflows.digest.prompts.docgen_prompts import (
    METADATA_PROMPT,
    REVIEWER_PROMPT,
    WRITER_PROMPT,
)

logger = structlog.get_logger()


def build_global_outline_summary(outline_tree: dict) -> str:
    """将目录树转为可读大纲文本。"""
    lines: list[str] = []
    for ch in outline_tree.get("chapters", []):
        lines.append(f"第{ch.get('chapter_index', '?')}章 {ch.get('title', '')}")
        for sec in ch.get("sections", []):
            lines.append(f"  - {sec.get('title', '')}")
    return "\n".join(lines)


async def write_chapter(
    *,
    chapter_title: str,
    chapter_index: int,
    total_chapters: int,
    global_outline_text: str,
    prev_summary: str,
    next_preview: str,
    source_content: str,
) -> str:
    """调用 Writer Agent 撰写单章 Markdown。"""
    max_src = 15000
    if len(source_content) > max_src:
        source_content = source_content[:max_src] + "\n\n（原始素材过长，已截取前半部分）"

    prompt = WRITER_PROMPT.format(
        global_outline=global_outline_text,
        chapter_title=chapter_title,
        chapter_index=chapter_index,
        total_chapters=total_chapters,
        prev_summary=prev_summary or "（本章为第一章，无上一节内容）",
        source_content=source_content,
        next_preview=next_preview or "（本章为最后一章，无后续内容）",
    )
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN,
        )
        return result.strip()
    except Exception as exc:
        logger.error("write_chapter_failed", chapter_index=chapter_index, error=str(exc))
        return f"# {chapter_title}\n\n> 📌 本章概要：本章节自动生成失败，以下为原始素材内容。\n\n{source_content}"


async def review_chapter(markdown: str, source_summary: str) -> dict:
    """调用 Reviewer Agent 质检单章。"""
    prompt = REVIEWER_PROMPT.format(
        document=markdown[:8000],
        source_summary=source_summary[:2000],
    )
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN_LIGHT,
        )
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(cleaned)
    except Exception as exc:
        logger.warning("review_chapter_failed", error=str(exc))
        return {"passed": True, "issues": [], "suggestions": []}


async def extract_metadata(markdown: str) -> dict:
    """LLM 提取章节 summary + tags。"""
    prompt = METADATA_PROMPT.format(document=markdown[:3000])
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN_LIGHT,
        )
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        meta = json.loads(cleaned)
        return {
            "summary": meta.get("summary", "")[:200],
            "tags": meta.get("tags", []),
        }
    except Exception as exc:
        logger.warning("extract_metadata_failed", error=str(exc))
        return {"summary": "", "tags": []}
