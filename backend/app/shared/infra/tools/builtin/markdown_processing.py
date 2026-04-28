"""Lightweight markdown processing helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlparse

from markdown_it import MarkdownIt

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
MERMAID_INFO_PATTERN = re.compile(
    r"^(mermaid|mindmap|graph|flowchart|sequencediagram|classdiagram|statediagram(?:-v2)?|erdiagram|gantt|pie|journey|timeline|gitgraph)\b",
    re.IGNORECASE,
)
RAW_MERMAID_FENCE_PATTERN = re.compile(
    r"(?m)^\s{0,3}```\s*(?:mermaid|mindmap|graph|flowchart|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|gantt|pie|journey|timeline|gitGraph)\b",
    re.IGNORECASE,
)
MALFORMED_MERMAID_FENCE_PATTERN = re.compile(r"^\s*```\s*(?P<trailing>.+)$")
INLINE_FENCE_PATTERN = re.compile(r"^(?P<prefix>.*\S)\s*```\s*(?P<lang>[A-Za-z0-9_-]*)\s*$")
STUCK_MATH_FENCE_PATTERN = re.compile(
    r"(?m)^(?P<prefix>\s*)\$\$[ \t]*(?P<fence>```[ \t]*[A-Za-z0-9_-]*[ \t]*)$"
)
BLOCKQUOTE_PREFIX_PATTERN = re.compile(r"^\s*>\s?")
MATH_FENCE_PATTERN = re.compile(r"^\s*(?:>\s*)?\$\$\s*$")
CALLOUT_LINE_PATTERN = re.compile(
    r"^(?P<indent>\s*)(?P<quote>>\s*)?\[!(?P<kind>NOTE|TIP|IMPORTANT|WARNING|CAUTION)\](?P<rest>.*)$",
    re.IGNORECASE,
)
BARE_CALLOUT_PATTERN = re.compile(
    r"(?m)^(?!\s*>)\s*\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]",
    re.IGNORECASE,
)
MATH_MARKDOWN_BOUNDARY_PATTERN = re.compile(
    r"^(?:#{1,6}\s+\S|[-*+]\s+(?:\*\*|`|\[|.{12,})|\d+\.\s+\S|>\s*\S|"
    r"\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]|\|.+\|.+\||```)",
    re.IGNORECASE,
)
INLINE_MATH_MARKDOWN_PATTERN = re.compile(
    r"(^|\n)\s*(?:#{1,6}\s+\S|[-*+]\s+(?:\*\*|`|\[|.{12,})|\d+\.\s+\S|>\s*\S|"
    r"\[!(?:NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]|\|.+\|.+\||```)",
    re.IGNORECASE,
)
_MARKDOWN_PARSER = MarkdownIt("commonmark")


def _trim_blank_lines(lines: list[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and not trimmed[0].strip():
        trimmed.pop(0)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def _append_callout_block(output: list[str], *, kind: str, body_lines: list[str]) -> None:
    body = _trim_blank_lines(body_lines)
    output.append(f"> [!{kind.upper()}]")
    if not body:
        return
    # react-markdown does not implement GitHub's callout extension. Keeping the
    # marker in its own blockquote paragraph lets the frontend recognize it
    # without flattening the marker and body into one ordinary quote paragraph.
    output.append(">")
    for body_line in body:
        output.append(f"> {body_line}" if body_line.strip() else ">")



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
    text = _split_stuck_math_fences(str(markdown or ""))
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


def _quoted_markdown_body(line: str) -> str | None:
    match = re.match(r"^\s*>\s?(.*)$", str(line or ""))
    if match is None:
        return None
    return str(match.group(1) or "").rstrip()


def _math_fence_prefix(line: str) -> str:
    match = re.match(r"^(\s*>\s*)?\$\$\s*$", str(line or ""))
    if match is None:
        return ""
    return str(match.group(1) or "")


def _normalize_math_fence_line(line: str) -> str:
    return f"{_math_fence_prefix(line)}$$"


def _collect_loose_display_math_block(lines: list[str], start_index: int) -> tuple[list[str], int]:
    body_lines = ["$$"]
    index = start_index + 1
    while index < len(lines):
        current = lines[index].rstrip()
        quoted = _quoted_markdown_body(current)
        body_line = quoted if quoted is not None else current
        body_lines.append(body_line)
        index += 1
        if MATH_FENCE_PATTERN.match(body_line):
            break
    return body_lines, index


def _is_markdown_boundary_inside_math(line: str) -> bool:
    stripped = _strip_quote_prefix(line).strip()
    if not stripped:
        return False
    return bool(MATH_MARKDOWN_BOUNDARY_PATTERN.match(stripped))


def _repair_display_math_boundaries(markdown: str) -> str:
    """Close display math before obvious Markdown blocks leak into it."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    in_math = False
    math_prefix = ""
    for raw_line in lines:
        line = raw_line.rstrip()
        if MATH_FENCE_PATTERN.match(line):
            delimiter_prefix = _math_fence_prefix(line)
            if in_math:
                fixed.append(f"{delimiter_prefix or math_prefix}$$")
                in_math = False
                math_prefix = ""
            else:
                math_prefix = delimiter_prefix
                fixed.append(f"{math_prefix}$$")
                in_math = True
            continue
        if in_math and _is_markdown_boundary_inside_math(line):
            closing_delimiter = f"{math_prefix}$$"
            if not fixed or fixed[-1] != closing_delimiter:
                fixed.append(closing_delimiter)
            in_math = False
            math_prefix = ""
        fixed.append(line)
    if in_math:
        fixed.append(f"{math_prefix}$$")
    return "\n".join(fixed)


def _repair_split_inline_code_math_literals(markdown: str) -> str:
    """Undo a known corruption from math cleanup touching inline code dollars."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        if (
            index + 3 < len(lines)
            and line.rstrip().endswith("`")
            and MATH_FENCE_PATTERN.match(lines[index + 1])
            and lines[index + 2].lstrip().startswith("`")
            and lines[index + 2].rstrip().endswith("$")
            and MATH_FENCE_PATTERN.match(lines[index + 3])
        ):
            tail = lines[index + 2].lstrip().rstrip()
            fixed.append(f"{line}$$" + tail[:-1])
            index += 4
            continue

        if (
            MATH_FENCE_PATTERN.match(line)
            and index + 1 < len(lines)
            and lines[index + 1].lstrip().startswith("```")
        ):
            previous = next((item.strip() for item in reversed(fixed) if item.strip()), "")
            if "示例" in previous or "代码" in previous or "命令" in previous:
                index += 1
                continue

        fixed.append(line)
        index += 1
    return "\n".join(fixed)


def _normalize_callout_blocks(markdown: str) -> str:
    """Convert GitHub callout variants to a frontend-stable blockquote shape."""

    lines = str(markdown or "").split("\n")
    output: list[str] = []
    in_fence = False
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            output.append(line)
            index += 1
            continue
        if in_fence:
            output.append(line)
            index += 1
            continue

        match = CALLOUT_LINE_PATTERN.match(line)
        if match is None:
            output.append(line)
            index += 1
            continue

        kind = str(match.group("kind") or "").upper()
        rest = str(match.group("rest") or "").strip()
        if match.group("quote"):
            body_lines: list[str] = [rest] if rest else []
            index += 1
            while index < len(lines):
                body_line = lines[index].rstrip()
                inner = _quoted_markdown_body(body_line)
                if inner is None:
                    if MATH_FENCE_PATTERN.match(body_line):
                        math_lines, index = _collect_loose_display_math_block(lines, index)
                        body_lines.extend(math_lines)
                        continue
                    if not body_line.strip():
                        next_line = lines[index + 1].rstrip() if index + 1 < len(lines) else ""
                        if _quoted_markdown_body(next_line) is not None or MATH_FENCE_PATTERN.match(next_line):
                            body_lines.append("")
                            index += 1
                            continue
                    break
                if inner.strip() and CALLOUT_LINE_PATTERN.match(inner):
                    break
                body_lines.append(inner)
                index += 1
            _append_callout_block(output, kind=kind, body_lines=body_lines)
            continue

        body_lines = [rest] if rest else []
        if rest:
            _append_callout_block(output, kind=kind, body_lines=body_lines)
            index += 1
            continue

        index += 1
        while index < len(lines):
            body_line = lines[index].rstrip()
            body_stripped = body_line.strip()
            if not body_stripped:
                output.append(">")
                index += 1
                break
            if body_stripped.startswith(("```", "---", "***", "___")) or re.match(r"^#{1,6}\s+\S", body_stripped):
                break
            if body_lines and body_stripped.startswith("**") and any(
                marker in body_stripped for marker in ("自测", "例题", "题目", "解析", "正确答案")
            ):
                break
            if CALLOUT_LINE_PATTERN.match(body_line):
                break
            body_lines.append(body_line)
            index += 1
        _append_callout_block(output, kind=kind, body_lines=body_lines)
    return "\n".join(output)


def _unescaped_single_dollar_positions(line: str) -> list[int]:
    positions: list[int] = []
    index = 0
    while index < len(line):
        if line[index] == "`":
            tick_count = 1
            while index + tick_count < len(line) and line[index + tick_count] == "`":
                tick_count += 1
            fence = "`" * tick_count
            closing = line.find(fence, index + tick_count)
            if closing >= 0:
                index = closing + tick_count
                continue
            index += tick_count
            continue
        if line[index] != "$":
            index += 1
            continue
        if index + 1 < len(line) and line[index + 1] == "$":
            index += 2
            continue
        if index > 0 and line[index - 1] == "\\":
            index += 1
            continue
        positions.append(index)
        index += 1
    return positions


def _inline_math_body_is_unsafe(body: str) -> bool:
    if "\n" in body:
        return True
    if len(body) > 240:
        return True
    if INLINE_MATH_MARKDOWN_PATTERN.search(body):
        return True
    return any(marker in body for marker in ("```", "`", "**", "[!", "<div", "</", "<table"))


def _find_unsafe_inline_math_spans(markdown: str) -> list[str]:
    issues: list[str] = []
    lines = str(markdown or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    in_fence = False
    in_math = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            continue
        if in_math:
            continue
        positions = _unescaped_single_dollar_positions(line)
        if len(positions) % 2 != 0:
            issues.append("存在未成对的单美元内联公式分隔符。")
            continue
        for left, right in zip(positions[0::2], positions[1::2], strict=False):
            if _inline_math_body_is_unsafe(line[left + 1 : right]):
                issues.append("内联公式疑似吞入 Markdown 正文。")
                break
    return issues


def _escape_unpaired_inline_dollars(markdown: str) -> str:
    """Escape dangling single dollar delimiters outside code/display math."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    in_fence = False
    in_math = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fixed.append(line)
            continue
        if in_fence:
            fixed.append(line)
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            fixed.append(_normalize_math_fence_line(line))
            continue
        if in_math:
            fixed.append(line)
            continue

        positions = _unescaped_single_dollar_positions(line)
        if len(positions) % 2 == 0:
            fixed.append(line)
            continue
        dangling = positions[-1]
        fixed.append(line[:dangling] + r"\$" + line[dangling + 1 :])
    return "\n".join(fixed)


def _escape_unsafe_inline_math_spans(markdown: str) -> str:
    """Escape paired inline math spans that clearly contain Markdown blocks."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    in_fence = False
    in_math = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fixed.append(line)
            continue
        if in_fence:
            fixed.append(line)
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            fixed.append(_normalize_math_fence_line(line))
            continue
        if in_math:
            fixed.append(line)
            continue

        positions = _unescaped_single_dollar_positions(line)
        if len(positions) < 2 or len(positions) % 2 != 0:
            fixed.append(line)
            continue

        rebuilt: list[str] = []
        cursor = 0
        changed = False
        for left, right in zip(positions[0::2], positions[1::2], strict=False):
            body = line[left + 1 : right]
            rebuilt.append(line[cursor:left])
            if _inline_math_body_is_unsafe(body):
                rebuilt.append(r"\$")
                rebuilt.append(body)
                rebuilt.append(r"\$")
                changed = True
            else:
                rebuilt.append(line[left : right + 1])
            cursor = right + 1
        rebuilt.append(line[cursor:])
        fixed.append("".join(rebuilt) if changed else line)
    return "\n".join(fixed)


def _trim_inline_math_padding(markdown: str) -> str:
    """Remove padding just inside paired single-dollar math delimiters."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    in_fence = False
    in_math = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fixed.append(line)
            continue
        if in_fence:
            fixed.append(line)
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            fixed.append(_normalize_math_fence_line(line))
            continue
        if in_math:
            fixed.append(line)
            continue

        positions = _unescaped_single_dollar_positions(line)
        if len(positions) < 2 or len(positions) % 2 != 0:
            fixed.append(line)
            continue

        rebuilt: list[str] = []
        cursor = 0
        changed = False
        for left, right in zip(positions[0::2], positions[1::2], strict=False):
            body = line[left + 1 : right]
            trimmed = body.strip()
            rebuilt.append(line[cursor:left])
            if trimmed and trimmed != body:
                rebuilt.append("$")
                rebuilt.append(trimmed)
                rebuilt.append("$")
                changed = True
            else:
                rebuilt.append(line[left : right + 1])
            cursor = right + 1
        rebuilt.append(line[cursor:])
        fixed.append("".join(rebuilt) if changed else line)
    return "\n".join(fixed)


def _normalize_list_embedded_headings(markdown: str) -> str:
    """Turn list items that accidentally contain Markdown headings back into text."""

    lines = str(markdown or "").split("\n")
    fixed: list[str] = []
    in_fence = False
    in_math = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            fixed.append(line)
            continue
        if in_fence:
            fixed.append(line)
            continue
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            fixed.append(_normalize_math_fence_line(line))
            continue
        if in_math:
            fixed.append(line)
            continue

        fixed.append(re.sub(r"^(\s*(?:[-*+]|\d+[.)])\s+)#{1,6}\s+(.+)$", r"\1\2", line))
    return "\n".join(fixed)


def normalize_markdown_rendering(markdown: str) -> str:
    """修复学生文档里最容易破坏渲染的 Markdown 结构。

    LLM 常见问题是把 display math 或 fenced code 混进 blockquote，
    例如 ``> ```dos`` 或 ``$$`` 内部行仍带 ``>``。这里做确定性清洗，
    不改知识内容，只修可渲染结构。
    """

    text = _split_stuck_math_fences(str(markdown or "").replace("\r\n", "\n").replace("\r", "\n"))
    text = _repair_split_inline_code_math_literals(text)
    text = _repair_display_math_boundaries(text)
    text = _escape_unpaired_inline_dollars(text)
    text = _escape_unsafe_inline_math_spans(text)
    text = _trim_inline_math_padding(text)
    text = _normalize_list_embedded_headings(text)
    text = _normalize_callout_blocks(text)
    if not text:
        return ""

    lines = text.split("\n")
    fixed: list[str] = []
    in_math = False
    math_prefix = ""
    in_fence = False

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if in_math:
            if MATH_FENCE_PATTERN.match(line):
                delimiter_prefix = _math_fence_prefix(line)
                fixed.append(f"{delimiter_prefix or math_prefix}$$")
                in_math = False
                math_prefix = ""
                continue
            cleaned_math_line = (
                line if math_prefix else _strip_quote_prefix(line) if BLOCKQUOTE_PREFIX_PATTERN.match(line) else line
            )
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
            delimiter_prefix = _math_fence_prefix(line)
            if not delimiter_prefix and fixed and fixed[-1].strip() == ">":
                fixed[-1] = ""
            fixed.append(f"{delimiter_prefix}$$")
            in_math = True
            math_prefix = delimiter_prefix
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
    if _display_math_fence_line_count(text) % 2 != 0:
        issues.append("display math 分隔符数量不成对。")
    if STUCK_MATH_FENCE_PATTERN.search(text):
        issues.append("display math 分隔符和代码围栏粘连。")
    if _display_math_contains_markdown(text):
        issues.append("display math 疑似吞入 Markdown 正文。")
    if BARE_CALLOUT_PATTERN.search(text):
        issues.append("GitHub callout 未使用 blockquote 语法。")
    issues.extend(_find_unsafe_inline_math_spans(text))
    if _raw_mermaid_fence_count(text) != _parsed_mermaid_fence_count(text):
        issues.append("Mermaid 代码围栏未被 Markdown 解析为独立代码块。")
    return list(dict.fromkeys(issues))


def _display_math_contains_markdown(markdown: str) -> bool:
    in_math = False
    for line in str(markdown or "").split("\n"):
        if MATH_FENCE_PATTERN.match(line):
            in_math = not in_math
            continue
        if in_math and _is_markdown_boundary_inside_math(line):
            return True
    return False


def _display_math_fence_line_count(markdown: str) -> int:
    return sum(1 for line in str(markdown or "").split("\n") if MATH_FENCE_PATTERN.match(line))


def _split_stuck_math_fences(markdown: str) -> str:
    return STUCK_MATH_FENCE_PATTERN.sub(
        lambda match: f"{match.group('prefix')}$$\n{match.group('prefix')}{match.group('fence').rstrip()}",
        str(markdown or ""),
    )


def _raw_mermaid_fence_count(markdown: str) -> int:
    return len(RAW_MERMAID_FENCE_PATTERN.findall(str(markdown or "")))


def _parsed_mermaid_fence_count(markdown: str) -> int:
    count = 0
    for token in _MARKDOWN_PARSER.parse(str(markdown or "")):
        if token.type != "fence":
            continue
        info = str(token.info or "").strip()
        if MERMAID_INFO_PATTERN.match(info):
            count += 1
    return count



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
