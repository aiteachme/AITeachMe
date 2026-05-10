"""Deterministic study-plan builder for the Profile study-plan lane.

This module turns current profile summaries into a short execution plan. It
does not plan source-material digestion; that responsibility belongs to
``digest/planner``.
"""

from __future__ import annotations

_EXAM_MODE_LABELS = {
    "web_practice": "网页练习",
    "paper_exam": "整卷练习",
}

_DIFFICULTY_LABELS = {
    "easy": "基础难度",
    "medium": "中等难度",
    "hard": "拔高难度",
    "mixed": "混合难度",
}

_QUESTION_TYPE_LABELS = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "fill_blank": "填空题",
    "short_answer": "简答题",
    "calculation": "计算题",
    "proof": "证明题",
}


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _label(mapping: dict[str, str], value: object, default: str) -> str:
    key = str(value or "").strip()
    return mapping.get(key, default)


def _question_type_labels(values: object) -> str:
    labels = [
        _QUESTION_TYPE_LABELS.get(str(item), "其他题型")
        for item in _as_list(values)[:2]
        if str(item or "").strip()
    ]
    return "、".join(labels)


def build_profile_study_plan(
    *,
    course_profile: dict[str, object] | None,
    user_profile: dict[str, object] | None,
) -> list[dict[str, object]]:
    """Build a compact learning plan from current profile summaries."""

    course = dict(course_profile or {})
    user = dict(user_profile or {})
    due_reviews = _as_int(course.get("due_review_count"))
    weak_count = _as_int(course.get("weak_knowledge_unit_count"))
    question_count = _as_int(course.get("recommended_question_count"), default=10)
    mode = _label(_EXAM_MODE_LABELS, course.get("recommended_exam_mode"), "网页练习")
    difficulty = _label(_DIFFICULTY_LABELS, course.get("difficulty_focus"), "中等难度")
    question_types = _question_type_labels(course.get("recommended_question_types"))
    explanation_style = str(user.get("explanation_style") or "balanced")

    review_detail = (
        f"先处理 {due_reviews} 个高优先级复习任务，避免遗忘继续扩大。"
        if due_reviews > 0
        else "先用 10 分钟快速回看最近薄弱知识点，确认今天练习范围。"
    )
    practice_detail = f"{mode} · 约 {question_count or 10} 题 · {difficulty}"
    if question_types:
        practice_detail += f" · {question_types}"
    practice_detail += "。"
    reflection_detail = (
        "用逐步推导式复盘错题，写下卡住的前一步。"
        if explanation_style == "detailed"
        else "用简短总结复盘错题，提炼 2 条可迁移规则。"
        if explanation_style == "concise"
        else "复盘错题时同时记录原因和下一次检查点。"
    )

    return [
        {
            "key": "review",
            "title": "先稳住遗忘风险",
            "detail": review_detail,
            "action": "review",
            "priority": 1 if due_reviews > 0 else 2,
            "source": "review_state",
        },
        {
            "key": "practice",
            "title": "再做定向练习",
            "detail": practice_detail,
            "action": "practice",
            "priority": 1 if weak_count > 0 else 2,
            "source": "course_profile",
        },
        {
            "key": "reflect",
            "title": "最后复盘讲解",
            "detail": reflection_detail,
            "action": "interact",
            "priority": 3,
            "source": "user_profile",
        },
    ]


__all__ = ["build_profile_study_plan"]
