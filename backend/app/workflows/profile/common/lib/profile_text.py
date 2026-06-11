"""Compact profile text renderers shared by profile consumers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_EXAM_MODE_LABELS = {
    "web_practice": "随练巩固",
    "paper_exam": "整卷检验",
}

_QUESTION_TYPE_LABELS = {
    "single_choice": "单选",
    "multiple_choice": "多选",
    "fill_blank": "填空",
    "short_answer": "简答",
    "calculation": "计算",
    "proof": "证明",
}

_EXPLANATION_LABELS = {
    "concise": "偏好直接结论和短解析",
    "balanced": "适合先给结构再解释细节",
    "guided": "更适合分步引导和追问式讲解",
}

_PACE_LABELS = {
    "quick_cycle": "近期练习较密集，适合短周期复盘",
    "steady": "适合稳定推进，边学边练",
    "deep_dive": "适合较长时间的系统讲解",
}

_CONSISTENCY_LABELS = {
    "high": "学习连续性较好",
    "steady": "学习节奏正在形成",
    "building": "学习节奏仍在建立",
}

_DIFFICULTY_LABELS = {
    "easy": "先补基础",
    "medium": "标准训练",
    "hard": "拔高突破",
    "mixed": "混合训练",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _list(value: Any, *, limit: int = 4) -> list[str]:
    items = value if isinstance(value, Sequence) and not isinstance(value, str) else [value]
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _labels(values: Sequence[str], mapping: Mapping[str, str]) -> str:
    return "、".join(mapping.get(value, value) for value in values if value)


def _pct(value: Any) -> str:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{round(max(0.0, min(1.0, parsed)) * 100)}%"


def render_user_profile_text(summary: Mapping[str, Any]) -> str:
    """Render a user-level profile into a short prompt-ready paragraph."""

    active_course_count = int(summary.get("active_course_count") or 0)
    question_types = _list(summary.get("preferred_question_types"), limit=3)
    exam_modes = _list(summary.get("preferred_exam_modes"), limit=2)
    notes = _list(summary.get("notes"), limit=3)
    lines = [
        f"用户画像：当前有 {active_course_count} 门活跃课程。" if active_course_count else "用户画像：暂无稳定课程数据。",
        _EXPLANATION_LABELS.get(_text(summary.get("explanation_style")), "讲解偏好尚不明确。"),
        _PACE_LABELS.get(_text(summary.get("pace_preference")), "学习节奏尚不明确。"),
        _CONSISTENCY_LABELS.get(_text(summary.get("consistency_level")), "学习连续性尚不明确。"),
    ]
    if question_types:
        lines.append(f"常练题型：{_labels(question_types, _QUESTION_TYPE_LABELS)}。")
    if exam_modes:
        lines.append(f"常用练习方式：{_labels(exam_modes, _EXAM_MODE_LABELS)}。")
    if notes:
        lines.append("补充信号：" + "；".join(notes) + "。")
    return " ".join(line for line in lines if line).strip()


def render_course_profile_text(summary: Mapping[str, Any], *, course_name: str = "") -> str:
    """Render a course-level profile into a short prompt-ready paragraph."""

    mastery = _pct(summary.get("avg_mastery"))
    weak_count = int(summary.get("weak_knowledge_unit_count") or 0)
    due_review_count = int(summary.get("due_review_count") or 0)
    recommended_types = _list(summary.get("recommended_question_types"), limit=3)
    notes = _list(summary.get("notes"), limit=3)
    prefix = f"课程画像（{course_name}）：" if course_name else "课程画像："
    lines = [prefix + (f"整体掌握度约 {mastery}。" if mastery else "掌握度数据仍在积累。")]
    if weak_count:
        lines.append(f"存在 {weak_count} 个薄弱知识点，文档应多给条件边界、例题和错因辨析。")
    if due_review_count:
        lines.append(f"有 {due_review_count} 个到期复习点，适合在相关章节加入短练习收束。")
    difficulty = _DIFFICULTY_LABELS.get(_text(summary.get("difficulty_focus")))
    if difficulty:
        lines.append(f"难度侧重：{difficulty}。")
    if recommended_types:
        lines.append(f"推荐题型：{_labels(recommended_types, _QUESTION_TYPE_LABELS)}。")
    if notes:
        lines.append("补充信号：" + "；".join(notes) + "。")
    return " ".join(line for line in lines if line).strip()


__all__ = ["render_course_profile_text", "render_user_profile_text"]
