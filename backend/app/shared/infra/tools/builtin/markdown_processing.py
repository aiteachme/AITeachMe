"""Lightweight markdown processing helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlparse

MERMAID_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[MERMAID:\s*(.+?)\]\s*-->")
IMAGE_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[IMAGE:\s*(.+?)\]\s*-->")
HEADER_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)



def extract_mermaid_placeholders(markdown: str) -> list[str]:
    return [match.strip() for match in MERMAID_PLACEHOLDER_PATTERN.findall(markdown)]



def extract_image_placeholders(markdown: str) -> list[str]:
    return [match.strip() for match in IMAGE_PLACEHOLDER_PATTERN.findall(markdown)]



def count_words(markdown: str) -> int:
    return len([token for token in re.split(r"\s+", markdown.strip()) if token])



def build_draft_excerpt(markdown: str, *, max_chars: int = 420) -> str:
    cleaned = re.sub(r"\s+", " ", markdown).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[: max_chars - 3].rstrip() + "..."


def extract_markdown_headers(
    markdown: str,
    *,
    min_level: int = 1,
    max_level: int = 6,
) -> list[dict[str, str | int]]:
    headers: list[dict[str, str | int]] = []
    for hashes, title in HEADER_PATTERN.findall(markdown):
        level = len(hashes)
        if level < min_level or level > max_level:
            continue
        cleaned_title = title.strip()
        lowered = cleaned_title.lower()
        if lowered in {"table of contents", "knowledge document overview", "目录", "知识文档总览"}:
            continue
        headers.append(
            {
                "level": level,
                "title": cleaned_title,
                "anchor": slugify_markdown_anchor(cleaned_title),
            }
        )
    return headers


def slugify_markdown_anchor(text: str) -> str:
    cleaned = text.strip().lower()
    cleaned = re.sub(r"[^\w\s-]", "", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-{2,}", "-", cleaned)
    return cleaned.strip("-")


def build_table_of_contents(
    markdown: str,
    *,
    heading: str = "## 目录",
    min_level: int = 1,
    max_level: int = 3,
    max_entries: int = 24,
) -> str:
    headers = extract_markdown_headers(markdown, min_level=min_level, max_level=max_level)
    if not headers:
        return ""
    lines = [heading, ""]
    base_level = min(int(item["level"]) for item in headers)
    for item in headers[:max_entries]:
        level = int(item["level"])
        indent = "  " * max(0, level - base_level)
        title = str(item["title"])
        anchor = str(item["anchor"])
        lines.append(f"{indent}- [{title}](#{anchor})")
    return "\n".join(lines).strip() + "\n"


def prepend_table_of_contents(
    markdown: str,
    *,
    heading: str = "## 目录",
    min_level: int = 1,
    max_level: int = 3,
    max_entries: int = 24,
) -> str:
    if heading.lower() in markdown.lower():
        return markdown
    toc = build_table_of_contents(
        markdown,
        heading=heading,
        min_level=min_level,
        max_level=max_level,
        max_entries=max_entries,
    ).strip()
    if not toc:
        return markdown
    return toc + "\n\n" + markdown.lstrip()



def normalize_source_details(source_details: list[Mapping[str, object]] | None) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in source_details or []:
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or "").strip()
        score = item.get("score")
        key = url or f"{title}::{source}"
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "url": url,
                "title": title or url or "Untitled source",
                "source": source,
                "score": f"{float(score):.3f}" if isinstance(score, (int, float)) else "",
            }
        )
    return normalized



def _format_source_bullet(item: Mapping[str, str]) -> str:
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or url or "Untitled source").strip()
    source = str(item.get("source") or "").strip()
    if url.startswith("local://") or not url:
        label = source or "local_material"
        return f"- {title} ({label})"
    domain = urlparse(url).netloc.strip()
    suffix = f" - {source}" if source else (f" - {domain}" if domain else "")
    return f"- [{title}]({url}){suffix}"



def build_reference_section(
    source_details: list[Mapping[str, object]] | None,
    *,
    heading: str = "## 参考资料与延伸阅读",
) -> str:
    normalized = normalize_source_details(source_details)
    if not normalized:
        return ""
    bullets = [_format_source_bullet(item) for item in normalized]
    return heading + "\n\n" + "\n".join(bullets).strip() + "\n"



def append_reference_section(
    markdown: str,
    source_details: list[Mapping[str, object]] | None,
    *,
    heading: str = "## 参考资料与延伸阅读",
) -> str:
    reference_block = build_reference_section(source_details, heading=heading).strip()
    if not reference_block:
        return markdown
    if heading.lower() in markdown.lower():
        return markdown
    return markdown.rstrip() + "\n\n" + reference_block + "\n"


__all__ = [
    "append_reference_section",
    "build_table_of_contents",
    "build_draft_excerpt",
    "build_reference_section",
    "count_words",
    "extract_image_placeholders",
    "extract_markdown_headers",
    "extract_mermaid_placeholders",
    "normalize_source_details",
    "prepend_table_of_contents",
    "slugify_markdown_anchor",
]
