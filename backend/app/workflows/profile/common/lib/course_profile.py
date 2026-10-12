"""Course-level profile aggregation for exam and tutoring hints."""

from __future__ import annotations

import json
from collections import Counter

from sqlmodel import Session, select

from app.models import ExamMode, ExamPaper, ExamPaperItem, Course, UserKnowledgeState
from app.repositories import profile_repo
from app.schemas.profile import CourseProfileSummary
from app.utils.time import is_at_or_before, utcnow
from app.workflows.profile.common.lib.conversation_memory import build_conversation_profile_signals
from app.workflows.profile.common.lib.profile_text import render_course_profile_text

_WEAK_THRESHOLD = 0.8
_RECENT_EXAM_ITEM_LIMIT = 200

_EXAM_MODE_LABELS = {
    ExamMode.WEB_PRACTICE.value: "网页练习",
    ExamMode.PAPER_EXAM.value: "整卷练习",
}

_QUESTION_TYPE_LABELS = {
    "single_choice": "单选题",
    "multiple_choice": "多选题",
    "fill_blank": "填空题",
    "short_answer": "简答题",
    "calculation": "计算题",
    "proof": "证明题",
}

_DIFFICULTY_LABELS = {
    "easy": "基础巩固",
    "medium": "标准训练",
    "hard": "拔高突破",
    "mixed": "混合训练",
}


def _parse_json_object(raw: str | None) -> dict[str, object]:
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _load_course_record(session: Session, *, course_id: str) -> Course | None:
    return session.exec(select(Course).where(Course.id == course_id)).first()


def _average_mastery(states: list[UserKnowledgeState]) -> float | None:
    if not states:
        return None
    return round(sum(state.mastery_score for state in states) / len(states), 4)


def _to_accuracy_map(
    totals: Counter[str],
    correct: Counter[str],
) -> dict[str, float]:
    return {
        key: round(correct.get(key, 0) / count, 4)
        for key, count in sorted(totals.items())
        if count > 0
    }


def _pick_preferred_question_types(type_totals: Counter[str]) -> list[str]:
    if not type_totals:
        return []
    ordered = sorted(type_totals.items(), key=lambda item: (-item[1], item[0]))
    return [question_type for question_type, _ in ordered[:3]]


def _pick_recommended_question_types(
    type_totals: Counter[str],
    type_accuracy: dict[str, float],
) -> list[str]:
    if not type_totals:
        return []

    ordered = sorted(
        type_totals.keys(),
        key=lambda question_type: (
            type_accuracy.get(question_type, 1.0),
            -type_totals.get(question_type, 0),
            question_type,
        ),
    )
    return ordered[:2]


def _pick_recommended_exam_mode(
    *,
    avg_mastery: float | None,
    weak_knowledge_unit_count: int,
    due_review_count: int,
) -> str:
    if due_review_count >= 2:
        return ExamMode.WEB_PRACTICE.value
    if avg_mastery is None or avg_mastery < 0.35:
        return ExamMode.WEB_PRACTICE.value
    if weak_knowledge_unit_count >= 6:
        return ExamMode.WEB_PRACTICE.value
    if avg_mastery >= 0.72 and weak_knowledge_unit_count <= 2:
        return ExamMode.PAPER_EXAM.value
    return ExamMode.WEB_PRACTICE.value


def _pick_recommended_question_count(
    *,
    recommended_exam_mode: str,
    weak_knowledge_unit_count: int,
    due_review_count: int,
) -> int:
    if recommended_exam_mode == ExamMode.PAPER_EXAM.value:
        return 24
    if due_review_count >= 2:
        return max(8, min(14, due_review_count * 2))
    return max(10, min(16, weak_knowledge_unit_count * 2 if weak_knowledge_unit_count > 0 else 10))


def _pick_difficulty_focus(
    *,
    avg_mastery: float | None,
    difficulty_accuracy: dict[str, float],
) -> str:
    if avg_mastery is None or avg_mastery < 0.35:
        return "easy"
    if difficulty_accuracy.get("hard", 1.0) < 0.5:
        return "medium"
    if avg_mastery >= 0.75:
        return "mixed"
    return "medium"


def _pick_focus_knowledge_unit_ids(knowledge_unit_states: list[UserKnowledgeState]) -> list[int]:
    ordered = sorted(
        [
            state
            for state in knowledge_unit_states
            if state.knowledge_unit_id is not None
        ],
        key=lambda state: (
            state.mastery_score,
            -state.review_priority,
            state.knowledge_unit_id or 0,
        ),
    )
    return [int(state.knowledge_unit_id) for state in ordered[:8] if state.knowledge_unit_id is not None]


def _build_notes(
    *,
    weak_knowledge_unit_count: int,
    due_review_count: int,
    recommended_exam_mode: str,
    recommended_question_types: list[str],
    difficulty_focus: str,
) -> list[str]:
    notes = [
        f"薄弱知识点：{weak_knowledge_unit_count} 个",
        f"到期复习：{due_review_count} 个",
        f"推荐练习模式：{_EXAM_MODE_LABELS.get(recommended_exam_mode, '网页练习')}",
    ]
    if recommended_question_types:
        notes.append(
            "推荐题型：" + "、".join(
                _QUESTION_TYPE_LABELS.get(question_type, "其他题型")
                for question_type in recommended_question_types
            )
        )
    notes.append(f"难度聚焦：{_DIFFICULTY_LABELS.get(difficulty_focus, '标准训练')}")
    return notes


def _load_recent_exam_items(
    session: Session,
    *,
    course_id: str,
    user_id: str,
) -> list[ExamPaperItem]:
    stmt = (
        select(ExamPaperItem)
        .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
        .where(
            ExamPaper.course_id == course_id,
            ExamPaper.user_id == user_id,
            ExamPaperItem.is_correct.is_not(None),
        )
        .order_by(ExamPaperItem.answered_at.desc(), ExamPaperItem.id.desc())
        .limit(_RECENT_EXAM_ITEM_LIMIT)
    )
    return list(session.exec(stmt).all())


def build_course_profile_summary(
    session: Session,
    *,
    course_id: str,
    user_id: str,
) -> CourseProfileSummary:
    knowledge_unit_states = profile_repo.list_knowledge_states(
        session,
        user_id=user_id,
        course_id=course_id,
        target_kind="knowledge_unit",
    )
    pending_reviews = profile_repo.list_pending_reviews(
        session,
        user_id=user_id,
        course_id=course_id,
    )
    now = utcnow()
    due_review_count = sum(
        1
        for state in pending_reviews
        if state.scheduled_review_at is None or is_at_or_before(state.scheduled_review_at, now)
    )

    recent_items = _load_recent_exam_items(
        session,
        course_id=course_id,
        user_id=user_id,
    )
    type_totals: Counter[str] = Counter()
    type_correct: Counter[str] = Counter()
    difficulty_totals: Counter[str] = Counter()
    difficulty_correct: Counter[str] = Counter()
    for item in recent_items:
        type_totals[item.question_type] += 1
        difficulty_totals[item.difficulty] += 1
        if item.is_correct:
            type_correct[item.question_type] += 1
            difficulty_correct[item.difficulty] += 1

    avg_mastery = _average_mastery(knowledge_unit_states)
    weak_knowledge_unit_count = sum(1 for state in knowledge_unit_states if state.mastery_score < _WEAK_THRESHOLD)
    question_type_accuracy = _to_accuracy_map(type_totals, type_correct)
    difficulty_accuracy = _to_accuracy_map(difficulty_totals, difficulty_correct)
    preferred_question_types = _pick_preferred_question_types(type_totals)
    recommended_question_types = _pick_recommended_question_types(
        type_totals,
        question_type_accuracy,
    )
    recommended_exam_mode = _pick_recommended_exam_mode(
        avg_mastery=avg_mastery,
        weak_knowledge_unit_count=weak_knowledge_unit_count,
        due_review_count=due_review_count,
    )
    difficulty_focus = _pick_difficulty_focus(
        avg_mastery=avg_mastery,
        difficulty_accuracy=difficulty_accuracy,
    )

    conversation_signals = build_conversation_profile_signals(
        session,
        user_id=user_id,
        course_id=course_id,
        limit=40,
    )

    course_record = _load_course_record(session, course_id=course_id)
    summary = CourseProfileSummary(
        course_id=course_id,
        generated_at=now,
        avg_mastery=avg_mastery,
        weak_knowledge_unit_count=weak_knowledge_unit_count,
        pending_review_count=len(pending_reviews),
        due_review_count=due_review_count,
        preferred_question_types=preferred_question_types,
        recommended_question_types=recommended_question_types,
        recommended_exam_mode=recommended_exam_mode,
        recommended_question_count=_pick_recommended_question_count(
            recommended_exam_mode=recommended_exam_mode,
            weak_knowledge_unit_count=weak_knowledge_unit_count,
            due_review_count=due_review_count,
        ),
        difficulty_focus=difficulty_focus,
        focus_knowledge_unit_ids=_pick_focus_knowledge_unit_ids(knowledge_unit_states),
        question_type_accuracy=question_type_accuracy,
        difficulty_accuracy=difficulty_accuracy,
        notes=[
            *_build_notes(
                weak_knowledge_unit_count=weak_knowledge_unit_count,
                due_review_count=due_review_count,
                recommended_exam_mode=recommended_exam_mode,
                recommended_question_types=recommended_question_types,
                difficulty_focus=difficulty_focus,
            ),
            *conversation_signals.notes,
        ],
    )
    summary.profile_text = render_course_profile_text(
        summary.model_dump(mode="python"),
        course_name=course_record.name if course_record is not None else "",
    )
    return summary


def load_course_profile_summary(
    session: Session,
    *,
    course_id: str,
) -> CourseProfileSummary | None:
    course_record = _load_course_record(session, course_id=course_id)
    if course_record is None:
        return None

    payload = _parse_json_object(course_record.profile_json)
    if not payload:
        return None

    try:
        return CourseProfileSummary.model_validate(payload)
    except Exception:
        return None


def refresh_course_profile_summary(
    session: Session,
    *,
    course_id: str,
    auto_commit: bool = True,
) -> CourseProfileSummary:
    course_record = _load_course_record(session, course_id=course_id)
    if course_record is None:
        raise ValueError(f"Course `{course_id}` not found.")

    summary = build_course_profile_summary(
        session,
        course_id=course_id,
        user_id=course_record.user_id,
    )
    course_record.profile_json = summary.model_dump_json()
    course_record.updated_at = utcnow()
    session.add(course_record)
    if auto_commit:
        session.commit()
        session.refresh(course_record)
    else:
        session.flush()
    return summary
