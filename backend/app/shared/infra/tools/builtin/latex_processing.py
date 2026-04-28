"""LaTeX normalization helpers."""

from __future__ import annotations

import re

_BLOCK_PATTERN = re.compile(r"\\\[([\s\S]*?)\\\]")
_INLINE_PATTERN = re.compile(r"\\\(([\s\S]*?)\\\)")
_FENCE_PATTERN = re.compile(r"(```[\s\S]*?```)")
_SINGLE_LINE_BLOCK_RE = re.compile(r"\$\$\s*([^\n$][\s\S]*?[^\n$])\s*\$\$")
_EMPTY_INLINE_RE = re.compile(r"(?<!\$)\$\s+\$(?!\$)")
_EMPTY_BLOCK_RE = re.compile(r"\$\$\s*\$\$")


def normalize_math_delimiters(markdown: str) -> str:
    """Normalize common model-produced math delimiters outside code fences."""

    return _process_non_fenced(markdown, _normalize_math_segment)


def validate_latex(markdown: str) -> str:
    """Repair obvious math delimiter issues without trying to prove LaTeX validity.

    The goal is display stability: do not alter code fences or Mermaid blocks,
    but prevent common LLM mistakes such as empty math spans, odd ``$$`` blocks,
    or a line ending with an unclosed inline ``$``.
    """

    return _process_non_fenced(markdown, _validate_math_segment)


def _process_non_fenced(markdown: str, processor) -> str:
    parts = _FENCE_PATTERN.split(str(markdown or ""))
    return "".join(part if part.startswith("```") else _process_non_inline_code(part, processor) for part in parts)


def _process_non_inline_code(segment: str, processor) -> str:
    """Apply math repairs outside inline code spans.

    DOS prompt strings and other command snippets often contain literal dollar
    signs, e.g. ``$P$G`` or ``$$``. Treating those inline-code dollars as LaTeX
    delimiters corrupts otherwise valid Markdown, so the math normalizer must
    leave code spans untouched.
    """

    text = str(segment or "")
    parts: list[str] = []
    cursor = 0
    length = len(text)
    while cursor < length:
        tick_index = text.find("`", cursor)
        if tick_index < 0:
            parts.append(processor(text[cursor:]))
            break
        parts.append(processor(text[cursor:tick_index]))
        tick_count = 1
        while tick_index + tick_count < length and text[tick_index + tick_count] == "`":
            tick_count += 1
        fence = "`" * tick_count
        closing = text.find(fence, tick_index + tick_count)
        if closing < 0:
            parts.append(text[tick_index:])
            break
        end = closing + tick_count
        parts.append(text[tick_index:end])
        cursor = end
    return "".join(parts)


def _normalize_math_segment(segment: str) -> str:
    normalized = _BLOCK_PATTERN.sub(lambda match: f"$$\n{match.group(1).strip()}\n$$", segment)
    normalized = _INLINE_PATTERN.sub(lambda match: f"${match.group(1).strip()}$", normalized)
    normalized = _SINGLE_LINE_BLOCK_RE.sub(lambda match: f"$$\n{match.group(1).strip()}\n$$", normalized)
    return normalized


def _validate_math_segment(segment: str) -> str:
    cleaned = _EMPTY_BLOCK_RE.sub("", segment)
    cleaned = _EMPTY_INLINE_RE.sub("", cleaned)
    cleaned = _separate_block_math(cleaned)
    cleaned = _close_unmatched_block_math(cleaned)
    keep_trailing_newline = cleaned.endswith("\n")
    lines = [_close_unmatched_inline_math(line) for line in cleaned.splitlines()]
    result = "\n".join(lines)
    if keep_trailing_newline and result and not result.endswith("\n"):
        result += "\n"
    return result


def _separate_block_math(segment: str) -> str:
    separated = re.sub(r"(?<!\n)\$\$", "\n$$", segment)
    separated = re.sub(r"\$\$(?!\n)", "$$\n", separated)
    return separated


def _close_unmatched_block_math(segment: str) -> str:
    if segment.count("$$") % 2 == 0:
        return segment
    return segment.rstrip() + "\n$$\n"


def _close_unmatched_inline_math(line: str) -> str:
    without_blocks = line.replace("$$", "")
    if without_blocks.count("$") % 2 == 0:
        return line
    if line.rstrip().endswith("$"):
        return line.replace("$", r"\$", 1)
    return line.rstrip() + "$"


__all__ = ["normalize_math_delimiters", "validate_latex"]
