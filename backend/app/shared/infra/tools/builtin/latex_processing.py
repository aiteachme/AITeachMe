"""LaTeX normalization helpers."""

from __future__ import annotations

import re

_BLOCK_PATTERN = re.compile(r"\\\[([\s\S]*?)\\\]")
_INLINE_PATTERN = re.compile(r"\\\(([\s\S]*?)\\\)")


def normalize_math_delimiters(markdown: str) -> str:
    normalized = _BLOCK_PATTERN.sub(lambda match: f"$$\n{match.group(1).strip()}\n$$", markdown)
    normalized = _INLINE_PATTERN.sub(lambda match: f"${match.group(1).strip()}$", normalized)
    return normalized


def validate_latex(markdown: str) -> str:
    # MVP: keep content stable and only normalize obvious delimiter mismatches.
    return markdown


__all__ = ["normalize_math_delimiters", "validate_latex"]
