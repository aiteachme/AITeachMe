"""Lightweight markdown processing helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlparse

MERMAID_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[MERMAID:\s*(.+?)\]\s*-->")
IMAGE_PLACEHOLDER_PATTERN = re.compile(r"<!--\s*\[IMAGE:\s*(.+?)\]\s*-->")
HEADER_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
KNOWLEDGE_ANCHOR_PATTERN = re.compile(
    r"\s*(?:\{#ku_[\w-]+\}|<!--\s*ATM_KU:\s*ku_[\w-]+\s*-->)"
)
MERMAID_START_PATTERN = re.compile(
    r"^(?P<prefix>(?:>\s*)*)```\s*(?P<lang>mermaid|mindmap|graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|timeline|gitGraph)?\s*$",
    re.IGNORECASE,
)
MERMAID_FENCE_PATTERN = re.compile(r"^```(?P<trailing>.*)$")
MARKDOWN_BOUNDARY_PATTERN = re.compile(r"^(#{1,6}\s+\S|[-*+]\s+\S|\d+\.\s+\S|>\s*\S|\|.+\||---\s*$)")
MERMAID_KEYWORD_PATTERN = re.compile(
    r"^(mindmap|graph|flowchart|sequencediagram|classdiagram|statediagram(?:-v2)?|erdiagram|gantt|pie|journey|timeline|gitgraph)\b",
    re.IGNORECASE,
)
MALFORMED_MERMAID_FENCE_PATTERN = re.compile(r"^\s*```\s*(?P<trailing>.+)$")
INLINE_FENCE_PATTERN = re.compile(r"^(?P<prefix>.*\S)\s*```\s*(?P<lang>[A-Za-z0-9_-]*)\s*$")
BLOCKQUOTE_PREFIX_PATTERN = re.compile(r"^\s*>\s?")
MATH_FENCE_PATTERN = re.compile(r"^\s*(?:>\s*)?\$\$\s*$")



def extract_mermaid_placeholders(markdown: str) -> list[str]:
    return [match.strip() for match in MERMAID_PLACEHOLDER_PATTERN.findall(markdown)]



def extract_image_placeholders(markdown: str) -> list[str]:
    return [match.strip() for match in IMAGE_PLACEHOLDER_PATTERN.findall(markdown)]



def count_words(markdown: str) -> int:
    compact = re.sub(r"\s+", "", markdown).strip()
    return len(compact)


def _strip_blockquote_prefix(line: str, *, prefix: str) -> str:
    candidate = str(line or "")
    if prefix and candidate.startswith(prefix):
        candidate = candidate[len(prefix) :]
    return re.sub(r"^(?:>\s*)+", "", candidate)


def _looks_like_mermaid_line(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped:
        return True
    if MERMAID_KEYWORD_PATTERN.match(stripped):
        return True
    if line.startswith((" ", "\t")):
        return True
    if stripped.startswith(("%%", ":::", "subgraph ", "style ", "classDef ", "class ", "click ", "section ", "title ")):
        return True
    if any(token in stripped for token in ("-->", "---", "==>", "|", "[", "]", "(", ")", "{", "}")):
        return True
    return False


def _looks_like_mermaid_garbage(line: str) -> bool:
    stripped = str(line or "").strip()
    if not stripped:
        return False
    return any(token in stripped for token in ("-->", "[", "]", "classDef", "subgraph"))


def _is_indented_context_echo(line: str) -> bool:
    if not line.startswith(("    ", "\t")):
        return False
    stripped = line.strip()
    if not stripped:
        return False
    return (
        stripped.startswith("#")
        or stripped.startswith(("```", "**", "✅", "🔥", ">", "|", "---"))
        or len(stripped) > 18
    )


def _is_malformed_mermaid_fence(line: str) -> bool:
    match = MALFORMED_MERMAID_FENCE_PATTERN.match(line)
    if match is None:
        return False
    trailing = (match.group("trailing") or "").strip()
    if not trailing:
        return False
    return _looks_like_mermaid_line(trailing) or _looks_like_mermaid_garbage(trailing)


def _append_mermaid_block(output_lines: list[str], block_lines: list[str]) -> None:
    body_lines = list(block_lines)
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    while body_lines and not body_lines[-1].strip():
        body_lines.pop()
    if not body_lines:
        return
    first_line = body_lines[0].strip()
    if not MERMAID_KEYWORD_PATTERN.match(first_line) and any(
        token in "\n".join(body_lines) for token in ("-->", "==>")
    ):
        body_lines.insert(0, "flowchart TD")
    output_lines.append("```mermaid")
    output_lines.extend(body_lines)
    output_lines.append("```")


def normalize_mermaid_blocks(markdown: str) -> str:
    text = str(markdown or "")
    if "```" not in text:
        return text

    original_has_trailing_newline = text.endswith("\n")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    normalized_lines: list[str] = []
    mermaid_lines: list[str] = []
    mermaid_prefix = ""
    in_mermaid = False
    after_mermaid_close = False
    skipping_artifact = False
    index = 0

    while index < len(lines):
        line = lines[index]
        stripped_line = line.strip()

        if skipping_artifact:
            if not stripped_line:
                index += 1
                continue
            if _is_indented_context_echo(line) or _is_malformed_mermaid_fence(line):
                index += 1
                continue
            if stripped_line.startswith("```"):
                skipping_artifact = False
                after_mermaid_close = False
                index += 1
                continue
            if MARKDOWN_BOUNDARY_PATTERN.match(stripped_line):
                skipping_artifact = False
                after_mermaid_close = False
                continue
            index += 1
            continue

        if not in_mermaid:
            if after_mermaid_close:
                if stripped_line == "```" or _is_indented_context_echo(line) or _is_malformed_mermaid_fence(line):
                    skipping_artifact = True
                    index += 1
                    continue
                after_mermaid_close = False
            start_match = MERMAID_START_PATTERN.match(line)
            lang = (start_match.group("lang") if start_match is not None else "") or ""
            if start_match and lang:
                in_mermaid = True
                mermaid_prefix = start_match.group("prefix") or ""
                normalized_lang = lang.strip()
                mermaid_lines = [] if normalized_lang.lower() == "mermaid" else [normalized_lang]
                index += 1
                continue
            malformed_match = MALFORMED_MERMAID_FENCE_PATTERN.match(line)
            malformed_trailing = (malformed_match.group("trailing") if malformed_match is not None else "") or ""
            if malformed_match is not None and _looks_like_mermaid_line(malformed_trailing):
                in_mermaid = True
                mermaid_prefix = ""
                mermaid_lines = [malformed_trailing.strip()]
                index += 1
                continue
            normalized_lines.append(line)
            index += 1
            continue

        if mermaid_lines and MARKDOWN_BOUNDARY_PATTERN.match(stripped_line):
            _append_mermaid_block(normalized_lines, mermaid_lines)
            mermaid_lines = []
            mermaid_prefix = ""
            in_mermaid = False
            after_mermaid_close = True
            continue

        cleaned_line = _strip_blockquote_prefix(line, prefix=mermaid_prefix).rstrip()
        fence_match = MERMAID_FENCE_PATTERN.match(cleaned_line.strip())
        if fence_match:
            _append_mermaid_block(normalized_lines, mermaid_lines)
            trailing = (fence_match.group("trailing") or "").strip()
            if trailing and not _looks_like_mermaid_garbage(trailing):
                normalized_lines.append(trailing)
            mermaid_lines = []
            mermaid_prefix = ""
            in_mermaid = False
            after_mermaid_close = True
            index += 1
            continue

        if mermaid_lines and not _looks_like_mermaid_line(cleaned_line):
            _append_mermaid_block(normalized_lines, mermaid_lines)
            mermaid_lines = []
            mermaid_prefix = ""
            in_mermaid = False
            after_mermaid_close = False
            continue

        mermaid_lines.append(cleaned_line)
        index += 1

    if in_mermaid:
        _append_mermaid_block(normalized_lines, mermaid_lines)

    normalized = "\n".join(normalized_lines)
    if original_has_trailing_newline and not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def _strip_quote_prefix(line: str) -> str:
    return BLOCKQUOTE_PREFIX_PATTERN.sub("", str(line or ""), count=1).rstrip()


def normalize_markdown_rendering(markdown: str) -> str:
    """修复学生文档里最容易破坏渲染的 Markdown 结构。

    LLM 常见问题是把 display math 或 fenced code 混进 blockquote，
    例如 ``> ```dos`` 或 ``$$`` 内部行仍带 ``>``。这里做确定性清洗，
    不改知识内容，只修可渲染结构。
    """

    text = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text:
        return ""

    lines = text.split("\n")
    fixed: list[str] = []
    in_math = False
    in_fence = False

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if in_math:
            if MATH_FENCE_PATTERN.match(line):
                fixed.append("$$")
                in_math = False
                continue
            cleaned_math_line = _strip_quote_prefix(line) if BLOCKQUOTE_PREFIX_PATTERN.match(line) else line
            if not cleaned_math_line.strip():
                continue
            fixed.append(cleaned_math_line)
            continue

        if in_fence:
            if stripped.startswith("```"):
                fixed.append("```")
                in_fence = False
                continue
            fixed.append(_strip_quote_prefix(line) if BLOCKQUOTE_PREFIX_PATTERN.match(line) else line)
            continue

        inline_fence = INLINE_FENCE_PATTERN.match(line)
        if inline_fence and not stripped.startswith("```"):
            prefix = inline_fence.group("prefix").rstrip()
            lang = inline_fence.group("lang").strip()
            if prefix:
                fixed.append(prefix)
            fixed.append(f"```{lang}".rstrip())
            in_fence = True
            continue

        if MATH_FENCE_PATTERN.match(line):
            if fixed and fixed[-1].strip() == ">":
                fixed[-1] = ""
            fixed.append("$$")
            in_math = True
            continue

        if stripped.startswith("> ```"):
            fixed.append("```" + stripped.removeprefix("> ```").strip())
            in_fence = True
            continue

        fixed.append(line)

    normalized = "\n".join(fixed)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    return normalized + ("\n" if normalized else "")


def find_markdown_rendering_issues(markdown: str) -> list[str]:
    """返回会影响 Markdown 渲染的结构问题。"""

    text = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    issues: list[str] = []
    if re.search(r"(?m)^>\s*.*```\s*[A-Za-z0-9_-]*\s*$", text):
        issues.append("代码块起始符被放在引用行内。")
    if re.search(r"(?m)^>\s*$\n\$\$", text) or re.search(r"(?m)^\$\$\n>\s*", text):
        issues.append("display math 内混入 blockquote 前缀。")
    if text.count("```") % 2 != 0:
        issues.append("Markdown fenced code block 数量不成对。")
    if text.count("$$") % 2 != 0:
        issues.append("display math 分隔符数量不成对。")
    return list(dict.fromkeys(issues))



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
        cleaned_title = KNOWLEDGE_ANCHOR_PATTERN.sub("", title).strip()
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
    cleaned = KNOWLEDGE_ANCHOR_PATTERN.sub("", text).strip().lower()
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
    "find_markdown_rendering_issues",
    "normalize_markdown_rendering",
    "normalize_source_details",
    "normalize_mermaid_blocks",
    "prepend_table_of_contents",
    "slugify_markdown_anchor",
]
