"""Planner brief parsing helpers."""

from __future__ import annotations

import re

from app.workflows.digest.planner.lib.models import PlannerBrief

_TASK_LINE_RE = re.compile(r"^\s*(?:[-*]|\(?\d+[).、])\s*(.+)$")
_INLINE_NUMBERED_RE = re.compile(r"^\s*\d+[.、)]\s*")


def _extract_labeled_line_payload(lines: list[str], label: str) -> str:
    for line in lines:
        cleaned = _INLINE_NUMBERED_RE.sub("", line).strip()
        if not cleaned.startswith(label):
            continue
        _, sep, value = cleaned.partition("：")
        if not sep:
            _, sep, value = cleaned.partition(":")
        return value.strip() if sep else ""
    return ""


def _split_inline_items(value: str, *, limit: int) -> list[str]:
    items: list[str] = []
    for raw in re.split(r"[；;]", value):
        item = _INLINE_NUMBERED_RE.sub("", raw).strip(" ：:，,。.-")
        if 3 <= len(item) <= 80 and "http" not in item.lower():
            items.append(item)
        if len(items) >= limit:
            break
    return items


def _fallback_items_from_lines(lines: list[str], *, limit: int) -> list[str]:
    items: list[str] = []
    for line in lines:
        match = _TASK_LINE_RE.match(line)
        if not match:
            continue
        candidate = match.group(1).strip()
        if 4 <= len(candidate) <= 80 and "http" not in candidate.lower():
            items.append(candidate)
        if len(items) >= limit:
            break
    return items


def parse_planner_brief_text(text: str, *, fallback: PlannerBrief) -> PlannerBrief:
    cleaned_lines = [line.strip() for line in str(text or "").replace("\r", "").splitlines() if line.strip()]
    focus_payload = _extract_labeled_line_payload(cleaned_lines, "关注重点")
    outline_payload = _extract_labeled_line_payload(cleaned_lines, "预计计划大纲")

    focus_points = _split_inline_items(focus_payload, limit=8) if focus_payload else []
    outline_items = _split_inline_items(outline_payload, limit=8) if outline_payload else []

    return PlannerBrief(
        markdown=text or fallback.markdown,
        focus_points=focus_points or _fallback_items_from_lines(cleaned_lines, limit=8) or fallback.focus_points,
        outline_items=outline_items or fallback.outline_items,
        clarifying_questions=fallback.clarifying_questions,
    )


__all__ = ["parse_planner_brief_text"]
