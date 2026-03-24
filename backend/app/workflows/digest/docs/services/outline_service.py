"""Pure helpers for outline planning in the docs lane."""

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

_MARKDOWN_HEADER_PATTERN = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)
_NUMBERED_HEADING_PATTERN = re.compile(
    r"^\s*(?:第[一二三四五六七八九十百千万0-9]+[章节讲部分]|[0-9]+(?:\.[0-9]+){0,2}|[一二三四五六七八九十]+)[、.．\s:：-]+(.+?)\s*$",
    re.MULTILINE,
)
_LATEX_BLOCK_PATTERN = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
_LATEX_INLINE_PATTERN = re.compile(r"\$([^$\n]{2,160})\$")
_SPACE_PATTERN = re.compile(r"\s+")
_PUNCT_ONLY_PATTERN = re.compile(r"^[\W_]+$")
_FORMULA_HINTS = (
    "=",
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


def _partition_items(items: list[str], bucket_count: int) -> list[list[str]]:
    if not items:
        return []

    normalized_bucket_count = max(1, min(bucket_count, len(items)))
    base_size, remainder = divmod(len(items), normalized_bucket_count)
    groups: list[list[str]] = []
    cursor = 0
    for bucket_index in range(normalized_bucket_count):
        take = base_size + (1 if bucket_index < remainder else 0)
        group = items[cursor: cursor + take]
        cursor += take
        if group:
            groups.append(group)
    return groups


def _clean_title(title: str) -> str:
    normalized = title.strip().strip("-").strip(":").strip("：").strip()
    normalized = _SPACE_PATTERN.sub(" ", normalized)
    return normalized[:40]


def _dedupe_titles(titles: list[str], *, limit: int = 8) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for raw in titles:
        title = _clean_title(raw)
        if (
            not title
            or len(title) < 2
            or len(title) > 40
            or _PUNCT_ONLY_PATTERN.match(title)
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
        normalized = _SPACE_PATTERN.sub(" ", raw).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def extract_headers(content: str) -> list[str]:
    """Extract headings from markdown or numbered lines."""

    markdown_headers = _MARKDOWN_HEADER_PATTERN.findall(content)
    numbered_headers = _NUMBERED_HEADING_PATTERN.findall(content)
    return _dedupe_titles([*markdown_headers, *numbered_headers], limit=12)


def infer_outline_candidates(content: str, *, source_filename: str) -> list[str]:
    """Infer lightweight section candidates without extra LLM calls."""

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
    """Build a short preview string for outline planning."""

    parts: list[str] = []
    for line in content.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if len(stripped) < 2:
            continue
        parts.append(stripped)
        joined = " ".join(parts)
        if len(joined) >= max_chars:
            return joined[:max_chars].rstrip()
    return " ".join(parts)[:max_chars].rstrip()


def extract_formula_candidates(content: str, *, limit: int = 8) -> list[str]:
    """Extract formula cues for chapter drafting and review."""

    formulas: list[str] = []
    for block in _LATEX_BLOCK_PATTERN.findall(content):
        normalized = block.strip()
        if normalized:
            formulas.append(f"$${normalized}$$")

    for inline in _LATEX_INLINE_PATTERN.findall(content):
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


def _estimate_single_chunk_chapter_count(content: str, titles: list[str]) -> int:
    title_count = len(titles)
    content_length = len(content.strip())
    if title_count >= 8:
        return 4
    if title_count >= 5:
        return 3
    if title_count >= 2:
        return 2
    if content_length >= 6000:
        return 4
    if content_length >= 3200:
        return 3
    if content_length >= 900:
        return 2
    return 1


def _build_outline_sections(titles: list[str], *, source_chunk_index: int) -> list[dict]:
    section_titles = _dedupe_titles(titles, limit=4) or ["核心内容"]
    return [
        {
            "title": title,
            "source_chunk_indices": [source_chunk_index],
        }
        for title in section_titles
    ]


def _build_single_chunk_outline(chunk: dict, local_outline: dict | None) -> dict:
    source_filename = str(chunk.get("source_filename", "未命名主题"))
    content = str(chunk.get("content", ""))
    local_titles = _dedupe_titles(list((local_outline or {}).get("titles", [])), limit=12)
    desired_chapter_count = _estimate_single_chunk_chapter_count(content, local_titles)

    if desired_chapter_count <= 1:
        chapter_title = (
            local_titles[0]
            if local_titles
            else infer_outline_candidates(content, source_filename=source_filename)[0]
        )
        section_titles = local_titles[1:4] or infer_outline_candidates(
            content,
            source_filename=source_filename,
        )[1:4]
        return {
            "chapters": [
                {
                    "chapter_index": 1,
                    "title": chapter_title,
                    "sections": _build_outline_sections(section_titles, source_chunk_index=0),
                }
            ]
        }

    content_batches = _split_content_batches(content, desired_chapter_count)
    grouped_titles = _partition_items(local_titles, len(content_batches))
    chapters: list[dict] = []
    for chapter_index, batch in enumerate(content_batches, start=1):
        title_group = grouped_titles[chapter_index - 1] if chapter_index - 1 < len(grouped_titles) else []
        batch_titles = infer_outline_candidates(batch, source_filename=source_filename)
        chapter_title = (
            title_group[0]
            if title_group
            else batch_titles[0]
            if batch_titles
            else f"{Path(source_filename).stem or '知识主题'} 第{chapter_index}部分"
        )
        section_titles = title_group[1:] or batch_titles[1:4]
        chapters.append(
            {
                "chapter_index": chapter_index,
                "title": chapter_title,
                "sections": _build_outline_sections(section_titles, source_chunk_index=0),
            }
        )
    return {"chapters": chapters}


def build_fallback_outline_tree(clean_chunks: list[dict], local_outlines: list[dict]) -> dict:
    """Build a deterministic fallback outline tree."""

    if not clean_chunks:
        return {"chapters": []}

    if len(clean_chunks) == 1:
        local_outline = local_outlines[0] if local_outlines else {}
        return _build_single_chunk_outline(clean_chunks[0], local_outline)

    chapters: list[dict] = []
    for index, chunk in enumerate(clean_chunks):
        local_outline = local_outlines[index] if index < len(local_outlines) else {}
        local_titles = _dedupe_titles(list(local_outline.get("titles", [])), limit=8)
        inferred_titles = infer_outline_candidates(
            str(chunk.get("content", "")),
            source_filename=str(chunk.get("source_filename", f"chunk_{index}")),
        )
        titles = local_titles or inferred_titles
        chapter_title = titles[0] if titles else f"第{index + 1}章"
        section_titles = titles[1:4] or inferred_titles[1:4]
        chapters.append(
            {
                "chapter_index": index + 1,
                "title": chapter_title,
                "sections": _build_outline_sections(section_titles, source_chunk_index=index),
            }
        )
    return {"chapters": chapters}


def ensure_multi_chapter_outline(
    outline_tree: dict,
    clean_chunks: list[dict],
    local_outlines: list[dict],
) -> dict:
    """Prevent a large source from collapsing into one weak chapter."""

    chapters = outline_tree.get("chapters", [])
    if not clean_chunks:
        return {"chapters": []}

    fallback_tree = build_fallback_outline_tree(clean_chunks, local_outlines)
    fallback_chapters = fallback_tree.get("chapters", [])
    if not chapters:
        return fallback_tree
    if len(chapters) >= 2:
        return outline_tree
    if len(fallback_chapters) >= 2:
        return fallback_tree
    return outline_tree


async def generate_local_titles(content: str) -> list[str]:
    """Generate local outline titles with a light model."""

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
            return _dedupe_titles([str(item) for item in titles], limit=6)
    except Exception as exc:
        logger.warning("generate_local_titles_failed", error=str(exc))
    return ["未分类内容"]


async def generate_global_outline(
    chunk_count: int,
    local_outlines_text: str,
    user_prompt: str | None = None,
) -> dict:
    """Generate the global outline tree with the main doc model."""

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


def build_chapter_assignments(outline_tree: dict, clean_chunks: list[dict]) -> list[dict]:
    """Build chapter assignments from the outline tree and cleaned chunks."""

    chapters = outline_tree.get("chapters", [])
    assignments: list[dict] = []
    chapter_source_sets: list[set[int]] = []
    for chapter in chapters:
        source_indices: set[int] = set()
        for section in chapter.get("sections", []):
            for index in section.get("source_chunk_indices", []):
                if 0 <= index < len(clean_chunks):
                    source_indices.add(index)
        chapter_source_sets.append(source_indices)

    chapter_specific_batches: dict[int, str] = {}
    chunk_to_chapter_positions: dict[int, list[int]] = {}
    for chapter_position, source_indices in enumerate(chapter_source_sets):
        if len(source_indices) != 1:
            continue
        chunk_index = next(iter(source_indices))
        chunk_to_chapter_positions.setdefault(chunk_index, []).append(chapter_position)

    for chunk_index, chapter_positions in chunk_to_chapter_positions.items():
        if len(chapter_positions) <= 1:
            continue
        if any(chapter_source_sets[position] != {chunk_index} for position in chapter_positions):
            continue
        chunk_content = str(clean_chunks[chunk_index]["content"])
        split_batches = _split_content_batches(chunk_content, len(chapter_positions))
        if len(split_batches) <= 1:
            continue
        for chapter_position, batch in zip(chapter_positions, split_batches):
            chapter_specific_batches[chapter_position] = batch

    for chapter_position, chapter in enumerate(chapters):
        chapter_index = chapter.get("chapter_index", 0)
        chapter_title = chapter.get("title", f"第{chapter_index}章")
        sections = chapter.get("sections", [])
        sorted_indices = sorted(chapter_source_sets[chapter_position])
        source_chunks = [clean_chunks[index] for index in sorted_indices]
        source_file_ids = [chunk.get("file_id", 0) for chunk in source_chunks]
        source_filenames = [str(chunk.get("source_filename", "")) for chunk in source_chunks]
        section_titles = [
            str(section.get("title", "")).strip()
            for section in sections
            if str(section.get("title", "")).strip()
        ]
        assigned_batch = chapter_specific_batches.get(chapter_position)
        source_contents = [assigned_batch] if assigned_batch is not None else [chunk["content"] for chunk in source_chunks]
        use_section_batches = len(source_contents) == 1 and len(sections) > 1
        section_batches = _split_content_batches(source_contents[0], len(sections)) if use_section_batches else []

        section_payloads: list[dict] = []
        for section_index, section in enumerate(sections, start=1):
            section_indices = [
                index
                for index in section.get("source_chunk_indices", [])
                if 0 <= index < len(clean_chunks)
            ]
            if use_section_batches and section_batches:
                batch = section_batches[min(section_index - 1, len(section_batches) - 1)]
                section_contents = [batch]
                section_file_ids = list(source_file_ids)
            else:
                section_contents = [clean_chunks[index]["content"] for index in section_indices]
                section_file_ids = [clean_chunks[index].get("file_id", 0) for index in section_indices]
                if not section_contents and source_contents:
                    section_contents = list(source_contents)
                    section_file_ids = list(source_file_ids)
            section_payloads.append(
                {
                    "section_index": section_index,
                    "title": section.get("title", f"第{section_index}节"),
                    "source_contents": section_contents,
                    "source_file_ids": section_file_ids,
                }
            )

        formula_refs: list[str] = []
        for source_content in source_contents:
            formula_refs.extend(extract_formula_candidates(source_content, limit=4))
        formula_refs = _dedupe_formula_refs(formula_refs, limit=10)

        brief_lines: list[str] = []
        if assigned_batch is not None and sorted_indices:
            index = sorted_indices[0]
            filename = str(source_chunks[0].get("source_filename", f"chunk_{index}"))
            preview = build_chunk_preview(assigned_batch, max_chars=180)
            brief_lines.append(f"- 材料块 {index} / {filename}: {preview}")
        else:
            for index, chunk in zip(sorted_indices, source_chunks):
                preview = build_chunk_preview(chunk["content"], max_chars=180)
                filename = str(chunk.get("source_filename", f"chunk_{index}"))
                brief_lines.append(f"- 材料块 {index} / {filename}: {preview}")

        assignments.append(
            {
                "chapter_index": chapter_index,
                "title": chapter_title,
                "sections": sections,
                "section_titles": section_titles,
                "section_payloads": section_payloads,
                "source_contents": source_contents,
                "source_file_ids": source_file_ids,
                "source_filenames": source_filenames,
                "source_brief": "\n".join(brief_lines) if brief_lines else "（无额外导读）",
                "formula_refs": formula_refs,
            }
        )

    return assignments
