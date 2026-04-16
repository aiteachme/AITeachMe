"""Planner sketch parsing helpers."""

from __future__ import annotations

import re

from app.workflows.digest.planner.lib.models import PlanSketch

_TASK_LINE_RE = re.compile(r"^\s*(?:[-*]|\(?\d+[).、])\s*(.+)$")
_HEADING_RE = re.compile(r"^##\s+(.+)$")
_INLINE_NUMBERED_RE = re.compile(r"^\s*\d+[.、)]\s*")


def _extract_section_lines(text: str, heading: str) -> list[str]:
    lines = [line.rstrip() for line in str(text or "").replace("\r", "").splitlines()]
    captured: list[str] = []
    current_heading = ""
    for line in lines:
        heading_match = _HEADING_RE.match(line.strip())
        if heading_match:
            current_heading = heading_match.group(1).strip()
            continue
        if current_heading == heading:
            if line.strip().startswith("## "):
                break
            captured.append(line)
    return captured


def _extract_first_blockquote_summary(text: str) -> str:
    lines = [line.strip() for line in str(text or "").replace("\r", "").splitlines()]
    summary_lines = [line.lstrip("> ").strip() for line in lines if line.startswith(">")]
    for line in summary_lines:
        if line.startswith("一句话摘要"):
            return line.split("：", 1)[-1].split(":", 1)[-1].strip()
    return summary_lines[-1] if summary_lines else ""


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


def parse_plan_sketch_text(text: str, *, fallback: PlanSketch) -> PlanSketch:
    cleaned_lines = [line.strip() for line in str(text or "").replace("\r", "").splitlines() if line.strip()]
    focus_payload = _extract_labeled_line_payload(cleaned_lines, "关注重点")
    outline_payload = _extract_labeled_line_payload(cleaned_lines, "预计计划大纲")
    tasks: list[str] = []
    if focus_payload:
        tasks = _split_inline_items(focus_payload, limit=8)
    if not tasks:
        task_lines = (
            _extract_section_lines(text, "思考重点")
            or _extract_section_lines(text, "研究任务")
            or cleaned_lines
        )
        for line in task_lines:
            match = _TASK_LINE_RE.match(line)
            if match:
                candidate = match.group(1).strip()
                if 4 <= len(candidate) <= 80 and "http" not in candidate.lower():
                    tasks.append(candidate)
            if len(tasks) >= 8:
                break

    chapters = _split_inline_items(outline_payload, limit=8) if outline_payload else []
    if not chapters:
        chapter_lines = _extract_section_lines(text, "计划大纲") or _extract_section_lines(text, "暂定章节")
        for line in chapter_lines:
            match = _TASK_LINE_RE.match(line.strip())
            if match:
                chapters.append(match.group(1).strip())

    assumptions = []
    for line in _extract_section_lines(text, "规划假设"):
        match = _TASK_LINE_RE.match(line.strip())
        if match:
            assumptions.append(match.group(1).strip())

    clarifications = []
    for line in _extract_section_lines(text, "待确认点"):
        match = _TASK_LINE_RE.match(line.strip())
        if match:
            clarifications.append(match.group(1).strip())

    title = cleaned_lines[0].lstrip("# ").strip() if cleaned_lines else fallback.title
    return PlanSketch(
        title=title[:40] or fallback.title,
        summary=_extract_first_blockquote_summary(text) or fallback.summary,
        research_tasks=tasks or fallback.research_tasks,
        provisional_chapters=chapters or fallback.provisional_chapters,
        assumptions=assumptions or fallback.assumptions,
        missing_clarifications=clarifications or fallback.missing_clarifications,
        raw_text=text or fallback.raw_text,
    )


__all__ = ["parse_plan_sketch_text"]
