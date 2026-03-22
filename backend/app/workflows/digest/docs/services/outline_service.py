"""大纲阶段纯函数服务。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import structlog

from app.core.llm import acompletion
from app.core.model_router import TaskType
from app.workflows.digest.kg.services.chunker import chunk_markdown
from app.workflows.digest.prompts.docgen_prompts import (
    GLOBAL_OUTLINE_PROMPT,
    LOCAL_OUTLINE_PROMPT,
)

logger = structlog.get_logger()

_MARKDOWN_HEADER_PAT = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_NUMBERED_HEADING_PAT = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百千万0-9]+[章节讲部分]|[0-9]+(?:\.[0-9]+){0,2}|[一二三四五六七八九十]+)[、.．\s:：\-]+(.+?)\s*$",
    re.MULTILINE,
)
_LATEX_BLOCK_PAT = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_LATEX_INLINE_PAT = re.compile(r"\$([^$\n]{2,160})\$")
_SPACE_PAT = re.compile(r"\s+")
_PUNCT_ONLY_PAT = re.compile(r"^[\W_]+$")
_FORMULA_HINTS = (
    "=",
    "→",
    "∫",
    "∑",
    "√",
    "lim",
    "sin",
    "cos",
    "tan",
    "ln",
    "log",
    "f(x)",
    "P(",
    "E(",
    "Var(",
)


def _split_content_batches(content: str, batch_count: int) -> list[str]:
    digest_chunks = [chunk.content.strip() for chunk in chunk_markdown(content) if chunk.content.strip()]
    if batch_count <= 1:
        return [content]
    if len(digest_chunks) <= 1:
        digest_chunks = [paragraph.strip() for paragraph in content.split("\n\n") if paragraph.strip()]
    if len(digest_chunks) <= 1:
        return [content]

    bucket_count = min(batch_count, len(digest_chunks))
    base_size, remainder = divmod(len(digest_chunks), bucket_count)
    batches: list[str] = []
    cursor = 0
    for bucket_index in range(bucket_count):
        take = base_size + (1 if bucket_index < remainder else 0)
        batch_chunks = digest_chunks[cursor: cursor + take]
        cursor += take
        if batch_chunks:
            batches.append("\n\n".join(batch_chunks).strip())
    return batches or [content]


def _clean_title(title: str) -> str:
    title = title.strip().strip("-").strip(":：").strip()
    title = _SPACE_PAT.sub(" ", title)
    return title[:40]


def _dedupe_titles(titles: list[str], *, limit: int = 8) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for raw in titles:
        title = _clean_title(raw)
        if (
            not title
            or len(title) < 2
            or len(title) > 40
            or _PUNCT_ONLY_PAT.match(title)
            or title in seen
        ):
            continue
        seen.add(title)
        deduped.append(title)
        if len(deduped) >= limit:
            break
    return deduped


def _dedupe_formula_refs(formulas: list[str], *, limit: int = 10) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in formulas:
        normalized = _SPACE_PAT.sub(" ", raw).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def extract_headers(content: str) -> list[str]:
    """从 Markdown 与常见编号行中提取标题。"""

    markdown_headers = _MARKDOWN_HEADER_PAT.findall(content)
    numbered_headers = _NUMBERED_HEADING_PAT.findall(content)
    return _dedupe_titles([*markdown_headers, *numbered_headers], limit=12)


def infer_outline_candidates(content: str, *, source_filename: str) -> list[str]:
    """轻量抽取一个材料块的章节候选。"""

    headers = extract_headers(content)
    if headers:
        return headers

    short_lines: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) <= 28 and stripped.count(" ") <= 4 and "。" not in stripped:
            short_lines.append(stripped)
        if len(short_lines) >= 6:
            break

    fallback = Path(source_filename).stem.replace("_", " ").replace("-", " ").strip() or "未命名主题"
    return _dedupe_titles([*short_lines, fallback], limit=6) or [fallback]


def build_chunk_preview(content: str, *, max_chars: int = 240) -> str:
    """构建给 outline reduce 使用的内容预览。"""

    parts: list[str] = []
    for line in content.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if not stripped:
            continue
        if len(stripped) < 2:
            continue
        parts.append(stripped)
        joined = " ".join(parts)
        if len(joined) >= max_chars:
            return joined[:max_chars].rstrip()
    return " ".join(parts)[:max_chars].rstrip()


def extract_formula_candidates(content: str, *, limit: int = 8) -> list[str]:
    """提取材料中的核心公式线索，供章节撰写和校验使用。"""

    formulas: list[str] = []

    for block in _LATEX_BLOCK_PAT.findall(content):
        normalized = block.strip()
        if normalized:
            formulas.append(f"$${normalized}$$")

    for inline in _LATEX_INLINE_PAT.findall(content):
        normalized = inline.strip()
        if normalized:
            formulas.append(f"${normalized}$")

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) > 120:
            continue
        if any(hint in stripped for hint in _FORMULA_HINTS) and len(re.findall(r"[A-Za-z0-9]", stripped)) >= 2:
            formulas.append(stripped)

    return _dedupe_formula_refs(formulas, limit=limit)


async def generate_local_titles(content: str) -> list[str]:
    """LLM 生成局部子标题。保留为兜底能力。"""

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
            return _dedupe_titles([str(t) for t in titles], limit=6)
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

        sorted_indices = sorted(source_indices)
        source_chunks = [clean_chunks[idx] for idx in sorted_indices]
        source_contents = [chunk["content"] for chunk in source_chunks]
        source_file_ids = [chunk.get("file_id", 0) for chunk in source_chunks]
        source_filenames = [str(chunk.get("source_filename", "")) for chunk in source_chunks]
        section_titles = [str(section.get("title", "")).strip() for section in sections if str(section.get("title", "")).strip()]
        use_section_batches = len(source_contents) == 1 and len(sections) > 1
        section_batches = _split_content_batches(source_contents[0], len(sections)) if use_section_batches else []

        section_payloads: list[dict] = []
        for section_index, section in enumerate(sections, start=1):
            section_indices = [
                idx for idx in section.get("source_chunk_indices", [])
                if 0 <= idx < len(clean_chunks)
            ]
            if use_section_batches:
                batch = section_batches[min(section_index - 1, len(section_batches) - 1)]
                section_contents = [batch]
                section_file_ids = list(source_file_ids)
            else:
                section_contents = [clean_chunks[idx]["content"] for idx in section_indices]
                section_file_ids = [clean_chunks[idx].get("file_id", 0) for idx in section_indices]
                if not section_contents and source_contents:
                    section_contents = list(source_contents)
                    section_file_ids = list(source_file_ids)

            section_payloads.append({
                "section_index": section_index,
                "title": section.get("title", f"第{section_index}节"),
                "source_contents": section_contents,
                "source_file_ids": section_file_ids,
            })

        formula_refs: list[str] = []
        for source_content in source_contents:
            formula_refs.extend(extract_formula_candidates(source_content, limit=4))
        formula_refs = _dedupe_formula_refs(formula_refs, limit=10)

        brief_lines: list[str] = []
        for idx, chunk in zip(sorted_indices, source_chunks):
            preview = build_chunk_preview(chunk["content"], max_chars=180)
            filename = str(chunk.get("source_filename", f"chunk_{idx}"))
            brief_lines.append(f"- 材料块 {idx} / {filename}: {preview}")

        assignments.append({
            "chapter_index": ch_index,
            "title": ch_title,
            "sections": sections,
            "section_titles": section_titles,
            "section_payloads": section_payloads,
            "source_contents": source_contents,
            "source_file_ids": source_file_ids,
            "source_filenames": source_filenames,
            "source_brief": "\n".join(brief_lines) if brief_lines else "（无额外导览）",
            "formula_refs": formula_refs,
        })

    return assignments
