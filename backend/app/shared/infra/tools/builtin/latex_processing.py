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
    return "".join(part if part.startswith("```") else processor(part) for part in parts)


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
    lines = [_close_unmatched_inline_math(line) for line in cleaned.splitlines()]
    return "\n".join(lines)


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
