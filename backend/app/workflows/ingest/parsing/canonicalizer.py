"""Markdown normalization helpers for ingest workflows."""

from __future__ import annotations

import re


_HEADING_RE = re.compile(r"^(#{1,6})\s*(.*)", re.MULTILINE)


def canonicalize_markdown(raw: str) -> str:
    """Normalize markdown into a stable downstream format."""

    if not raw:
        return ""

    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^(#{1,6})([^\s#])", r"\1 \2", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*[-*])([^\s])", r"\1 \2", text, flags=re.MULTILINE)
    text = re.sub(r"^(\s*\d+\.)([^\s])", r"\1 \2", text, flags=re.MULTILINE)
    text = _normalize_heading_levels(text)

    cleaned: list[str] = []
    prev_blank = False
    for line in (item.rstrip() for item in text.splitlines()):
        is_blank = line == ""
        if is_blank and prev_blank:
            continue
        cleaned.append(line)
        prev_blank = is_blank

    while cleaned and cleaned[0] == "":
        cleaned.pop(0)
    while cleaned and cleaned[-1] == "":
        cleaned.pop()

    result = "\n".join(cleaned)
    if result and not result.endswith("\n"):
        result += "\n"
    return result


def _normalize_heading_levels(text: str) -> str:
    """Keep heading levels continuous so downstream chunking is more stable."""

    levels_used = {len(match.group(1)) for match in _HEADING_RE.finditer(text)}
    if not levels_used:
        return text

    sorted_levels = sorted(levels_used)
    level_map = {
        old_level: min(new_level, 6)
        for new_level, old_level in enumerate(sorted_levels, start=1)
    }
    if all(old_level == new_level for old_level, new_level in level_map.items()):
        return text

    def _replace_heading(match: re.Match[str]) -> str:
        old_level = len(match.group(1))
        new_level = level_map.get(old_level, old_level)
        return f"{'#' * new_level} {match.group(2)}"

    return _HEADING_RE.sub(_replace_heading, text)
