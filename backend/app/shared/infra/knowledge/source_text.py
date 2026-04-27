"""Source text line-span helpers shared by knowledge workflows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LineSpan:
    """One-based inclusive line span inside a source text."""

    start_line: int
    end_line: int
    start_offset: int
    end_offset: int


def line_span_for_excerpt(source_text: str, excerpt: str, *, start_offset: int = 0) -> LineSpan | None:
    """Locate an excerpt in source text and return one-based inclusive lines.

    The helper intentionally stays pure: callers own storage, permissions, and
    workflow-specific section identity. It is useful for both "read exact
    source lines" and "attach line ranges to LLM-selected material slices".
    """

    source = str(source_text or "")
    needle = str(excerpt or "").strip()
    if not source or not needle:
        return None

    cursor = max(0, int(start_offset or 0))
    match_at = source.find(needle, cursor)
    if match_at < 0 and cursor > 0:
        match_at = source.find(needle)
    if match_at < 0:
        compact_needle = " ".join(needle.split())[:160]
        if compact_needle:
            compact_source = " ".join(source.split())
            compact_at = compact_source.find(compact_needle)
            if compact_at >= 0:
                return None
        return None

    end_at = match_at + len(needle)
    start_line = source.count("\n", 0, match_at) + 1
    end_line = source.count("\n", 0, max(match_at, end_at - 1)) + 1
    return LineSpan(
        start_line=start_line,
        end_line=max(start_line, end_line),
        start_offset=match_at,
        end_offset=end_at,
    )


def extract_line_span(
    source_text: str,
    *,
    start_line: int,
    end_line: int,
    context_lines: int = 0,
    max_chars: int | None = None,
) -> str:
    """Extract a one-based inclusive line span from source text."""

    lines = str(source_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines:
        return ""
    start = max(1, int(start_line or 1) - max(0, int(context_lines or 0)))
    end = min(len(lines), max(start, int(end_line or start_line or start)) + max(0, int(context_lines or 0)))
    excerpt = "\n".join(lines[start - 1 : end]).strip()
    if max_chars is not None and len(excerpt) > max_chars:
        return excerpt[: max(0, int(max_chars) - 3)].rstrip() + "..."
    return excerpt


def number_lines(excerpt: str, *, start_line: int = 1) -> str:
    """Prefix excerpt lines with source line numbers for prompt-facing context."""

    base = max(1, int(start_line or 1))
    return "\n".join(
        f"L{base + index}: {line}"
        for index, line in enumerate(str(excerpt or "").splitlines())
    )


__all__ = ["LineSpan", "extract_line_span", "line_span_for_excerpt", "number_lines"]
