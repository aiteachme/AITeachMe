"""Planner sketch parsing helpers."""

from __future__ import annotations

import re

from app.workflows.digest.planner.lib.research_probe import PlanSketch

_TASK_LINE_RE = re.compile(r"^\s*(?:[-*]|\(?\d+[).、])\s*(.+)$")
_HEADING_RE = re.compile(r"^##\s+(.+)$")


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


def parse_plan_sketch_text(text: str, *, fallback: PlanSketch) -> PlanSketch:
    cleaned_lines = [line.strip() for line in str(text or "").replace("\r", "").splitlines() if line.strip()]
    tasks: list[str] = []
    for line in _extract_section_lines(text, "研究任务") or cleaned_lines:
        match = _TASK_LINE_RE.match(line)
        if match:
            candidate = match.group(1).strip()
            if 4 <= len(candidate) <= 80 and "http" not in candidate.lower():
                tasks.append(candidate)
        if len(tasks) >= 8:
            break

    chapters = []
    for line in _extract_section_lines(text, "暂定章节"):
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
