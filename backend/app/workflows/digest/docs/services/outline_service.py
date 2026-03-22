"""大纲阶段纯函数服务。"""

from __future__ import annotations

import json

import structlog

from app.core.llm import acompletion
from app.core.model_router import TaskType
from app.workflows.digest.prompts.docgen_prompts import (
    GLOBAL_OUTLINE_PROMPT,
    LOCAL_OUTLINE_PROMPT,
)

logger = structlog.get_logger()


def extract_headers(content: str) -> list[str]:
    """从 Markdown 中提取 H1/H2/H3 标题。"""
    headers: list[str] = []
    for line in content.split("\n"):
        s = line.strip()
        if s.startswith("#"):
            title = s.lstrip("#").strip()
            if title:
                headers.append(title)
    return headers


async def generate_local_titles(content: str) -> list[str]:
    """LLM 生成局部子标题。"""
    prompt = LOCAL_OUTLINE_PROMPT.format(text=content[:3000])
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN_LIGHT,
        )
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        titles = json.loads(cleaned)
        if isinstance(titles, list):
            return [str(t) for t in titles[:5]]
    except Exception as exc:
        logger.warning("generate_local_titles_failed", error=str(exc))
    return ["未分类内容"]


async def generate_global_outline(
    chunk_count: int,
    local_outlines_text: str,
    user_prompt: str | None = None,
) -> dict:
    """LLM 全局统筹生成目录树。"""
    prompt = GLOBAL_OUTLINE_PROMPT.format(
        chunk_count=chunk_count,
        local_outlines=local_outlines_text,
        user_prompt=user_prompt or "（无额外要求）",
    )
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN,
        )
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        return json.loads(cleaned)
    except Exception as exc:
        logger.error("generate_global_outline_failed", error=str(exc))
        raise


def build_chapter_assignments(
    outline_tree: dict,
    clean_chunks: list[dict],
) -> list[dict]:
    """根据目录树和清洗文本块组装 chapter_assignments。"""
    chapters = outline_tree.get("chapters", [])
    assignments: list[dict] = []

    for chapter in chapters:
        ch_index = chapter.get("chapter_index", 0)
        ch_title = chapter.get("title", f"第{ch_index}章")
        sections = chapter.get("sections", [])

        source_indices: set[int] = set()
        for section in sections:
            for idx in section.get("source_chunk_indices", []):
                if 0 <= idx < len(clean_chunks):
                    source_indices.add(idx)

        source_contents = [clean_chunks[idx]["content"] for idx in sorted(source_indices)]
        source_file_ids = [clean_chunks[idx].get("file_id", 0) for idx in sorted(source_indices)]

        assignments.append({
            "chapter_index": ch_index,
            "title": ch_title,
            "sections": sections,
            "source_contents": source_contents,
            "source_file_ids": source_file_ids,
        })

    return assignments
