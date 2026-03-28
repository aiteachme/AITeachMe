"""Pure helpers for writing, reviewing, and tagging docs chapters."""

from __future__ import annotations

import json
import re

import structlog

from app.platform.llm import acompletion
from app.platform.model_router import TaskType
from app.workflows.digest.prompts.docgen_prompts import (
    METADATA_PROMPT,
    REVIEWER_PROMPT,
    WRITER_PROMPT,
)

logger = structlog.get_logger()

SUMMARY_PATTERN = re.compile(r"^>\s*📌\s*本章概要[:：]\s*(.+)$", re.MULTILINE)
TAG_PATTERN = re.compile(r"^📊\s*本章标签[:：]\s*(.+)$", re.MULTILINE)
H1_PATTERN = re.compile(r"^\s*#\s+.+$", re.MULTILINE)
H2_PATTERN = re.compile(r"^\s*##\s+(.+?)\s*$", re.MULTILINE)
SPACE_PATTERN = re.compile(r"\s+")


def analyze_chapter_structure(markdown: str) -> dict[str, bool]:
    """Check whether a generated chapter has the expected scaffold."""

    normalized = markdown.strip()
    return {
        "has_h1": bool(H1_PATTERN.search(normalized)),
        "has_h2": bool(H2_PATTERN.search(normalized)),
        "has_summary": bool(SUMMARY_PATTERN.search(normalized)),
        "has_tags": bool(TAG_PATTERN.search(normalized)),
    }


def build_global_outline_summary(outline_tree: dict) -> str:
    """Convert an outline tree into readable summary text."""

    lines: list[str] = []
    for chapter in outline_tree.get("chapters", []):
        lines.append(f"第{chapter.get('chapter_index', '?')}章 {chapter.get('title', '')}")
        for section in chapter.get("sections", []):
            lines.append(f"  - {section.get('title', '')}")
    return "\n".join(lines)


def _clean_json_payload(payload: str) -> str:
    cleaned = payload.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return cleaned


def _normalize_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    for tag in tags:
        stripped = re.sub(r"\s+", "", tag).lstrip("#")
        if not stripped:
            continue
        value = f"#{stripped[:16]}"
        if value not in normalized:
            normalized.append(value)
        if len(normalized) >= 5:
            break
    return normalized


def _derive_summary(chapter_title: str, section_titles: list[str], formula_refs: list[str]) -> str:
    if section_titles:
        preview = "、".join(title.strip() for title in section_titles[:3] if title.strip())
        return f"本章围绕{preview}展开，帮助你建立关于{chapter_title}的整体理解与复习抓手。"
    if formula_refs:
        return f"本章聚焦{chapter_title}中的关键公式与概念关系，强调定义、推导思路与典型应用。"
    return f"本章系统梳理{chapter_title}的核心知识点，方便你快速把握主线、方法与易错处。"


def _derive_tags(chapter_title: str, section_titles: list[str], markdown: str = "") -> list[str]:
    heading_tags = H2_PATTERN.findall(markdown)
    candidates = [chapter_title, *section_titles, *heading_tags]
    tags = _normalize_tags(candidates)
    return tags or ["#核心知识"]


def _summarize_source(source_content: str, *, max_chars: int) -> str:
    normalized = SPACE_PATTERN.sub(" ", source_content.replace("\n", " ")).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "..."


def _fallback_body(source_content: str) -> list[str]:
    paragraphs = [
        paragraph.strip()
        for paragraph in source_content.split("\n\n")
        if paragraph.strip()
    ]
    if not paragraphs:
        return ["原始素材较少，本章建议回看源文件补充细节。"]
    return [_summarize_source(paragraph, max_chars=260) for paragraph in paragraphs[:4]]


def _build_fallback_chapter(
    *,
    chapter_title: str,
    section_titles: list[str],
    formula_refs: list[str],
    source_content: str,
) -> str:
    summary = _derive_summary(chapter_title, section_titles, formula_refs)
    lines = [
        f"# {chapter_title}",
        "",
        f"> 📌 本章概要：{summary}",
        "",
        "## 核心内容",
        "",
    ]
    for paragraph in _fallback_body(source_content):
        lines.append(paragraph)
        lines.append("")

    if formula_refs:
        lines.extend(
            [
                "## 关键公式",
                "",
                *[f"- `{formula}`" for formula in formula_refs[:8]],
                "",
            ]
        )

    lines.extend(
        [
            "## 复习建议",
            "",
            "- 先抓定义和概念边界，再回到公式与例题。",
            "- 复习时优先核对关键条件、常见误区和典型问法。",
            "",
            f"📊 本章标签：{' '.join(_derive_tags(chapter_title, section_titles))}",
        ]
    )
    return "\n".join(lines).strip()


def _normalize_markdown(
    markdown: str,
    *,
    chapter_title: str,
    section_titles: list[str],
    formula_refs: list[str],
) -> str:
    lines = markdown.strip().splitlines()
    normalized_lines: list[str] = []
    seen_h1 = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            if seen_h1:
                normalized_lines.append(f"## {stripped[2:].strip()}")
                continue
            normalized_lines.append(f"# {chapter_title}")
            seen_h1 = True
            continue
        normalized_lines.append(line)

    normalized = "\n".join(normalized_lines).strip()
    if not seen_h1:
        normalized = f"# {chapter_title}\n\n{normalized}".strip()

    if not SUMMARY_PATTERN.search(normalized):
        summary = _derive_summary(chapter_title, section_titles, formula_refs)
        normalized = normalized.replace(
            f"# {chapter_title}",
            f"# {chapter_title}\n\n> 📌 本章概要：{summary}",
            1,
        )

    if not H2_PATTERN.search(normalized):
        normalized = f"{normalized}\n\n## 核心内容\n\n{_summarize_source(normalized, max_chars=320)}".strip()

    if not TAG_PATTERN.search(normalized):
        tags = " ".join(_derive_tags(chapter_title, section_titles, normalized))
        normalized = f"{normalized}\n\n📊 本章标签：{tags}".strip()

    return normalized


async def write_chapter(
    *,
    chapter_title: str,
    chapter_index: int,
    total_chapters: int,
    global_outline_text: str,
    section_titles: list[str],
    user_prompt: str | None,
    prev_summary: str,
    next_preview: str,
    source_brief: str,
    formula_refs: list[str],
    source_content: str,
    subject_context: str = "",
    teaching_style_hint: str = "",
) -> str:
    """Write one chapter with the main doc model."""

    truncated_source = source_content
    if len(truncated_source) > 18000:
        truncated_source = truncated_source[:18000] + "\n\n（原始素材过长，以上为核心截断内容）"

    prompt = WRITER_PROMPT.format(
        global_outline=global_outline_text or "（暂无全局大纲）",
        chapter_title=chapter_title,
        chapter_index=chapter_index,
        total_chapters=total_chapters,
        section_titles="、".join(section_titles) or "（待归纳）",
        user_prompt=user_prompt or "（无额外要求）",
        prev_summary=prev_summary or "（这是第一章，无上一章内容）",
        next_preview=next_preview or "（这是最后一章，无下一章预告）",
        source_brief=source_brief or "（无额外导读）",
        formula_refs="\n".join(f"- {formula}" for formula in formula_refs[:8]) or "（本章未抽取到明确公式）",
        source_content=truncated_source,
        subject_context=subject_context or "（未识别学科）",
        teaching_style_hint=teaching_style_hint or "（无特殊风格要求）",
    )

    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN,
        )
    except Exception as exc:
        logger.error("write_chapter_failed", chapter_index=chapter_index, error=str(exc))
        return _build_fallback_chapter(
            chapter_title=chapter_title,
            section_titles=section_titles,
            formula_refs=formula_refs,
            source_content=truncated_source,
        )

    return _normalize_markdown(
        result.strip(),
        chapter_title=chapter_title,
        section_titles=section_titles,
        formula_refs=formula_refs,
    )


async def review_chapter(
    markdown: str,
    source_summary: str,
    *,
    user_prompt: str | None = None,
    subject_context: str = "",
) -> dict:
    """Run one review pass for a drafted chapter."""

    prompt = REVIEWER_PROMPT.format(
        document=markdown[:9000],
        source_summary=source_summary[:2500],
        user_prompt=user_prompt or "（无额外要求）",
        subject_context=subject_context or "（未识别学科）",
    )
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN_LIGHT,
        )
        parsed = json.loads(_clean_json_payload(result))
    except Exception as exc:
        logger.warning("review_chapter_failed", error=str(exc))
        return {"passed": True, "issues": [], "suggestions": []}

    return {
        "passed": bool(parsed.get("passed", False)),
        "issues": [str(item) for item in parsed.get("issues", [])[:8]],
        "suggestions": [str(item) for item in parsed.get("suggestions", [])[:8]],
    }


def extract_metadata_rule_based(markdown: str) -> dict:
    """Extract summary and tags from the generated chapter structure."""

    summary_match = SUMMARY_PATTERN.search(markdown)
    tag_match = TAG_PATTERN.search(markdown)
    summary = summary_match.group(1).strip()[:200] if summary_match else ""
    tags = _normalize_tags(tag_match.group(1).split()) if tag_match else []

    if not summary:
        paragraphs = [
            line.strip()
            for line in markdown.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        summary = _summarize_source("\n".join(paragraphs[:2]), max_chars=80)

    if not tags:
        h1_match = H1_PATTERN.search(markdown)
        chapter_title = h1_match.group(0).replace("#", "", 1).strip() if h1_match else "核心知识"
        tags = _derive_tags(chapter_title, H2_PATTERN.findall(markdown), markdown)

    return {
        "summary": summary[:200],
        "tags": tags[:5],
    }


async def extract_metadata(markdown: str) -> dict:
    """Use a light model to extract summary and tags."""

    prompt = METADATA_PROMPT.format(document=markdown[:4000])
    try:
        result = await acompletion(
            [{"role": "user", "content": prompt}],
            task_type=TaskType.DOCGEN_LIGHT,
        )
        parsed = json.loads(_clean_json_payload(result))
    except Exception as exc:
        logger.warning("extract_metadata_failed", error=str(exc))
        return {"summary": "", "tags": []}

    return {
        "summary": str(parsed.get("summary", ""))[:200],
        "tags": _normalize_tags([str(tag) for tag in parsed.get("tags", [])]),
    }
