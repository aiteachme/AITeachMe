"""Profile-oriented repository helpers backed by the new schema."""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, select

from app.models import (
    ExamPaper,
    ExamPaperItem,
    KnowledgeNode,
    ReviewTask,
    Subject,
    TeachingUnit,
    User,
    UserAnswerAttempt,
    UserKnowledgeState,
)
from app.utils.time import utcnow


@dataclass(frozen=True)
class LegacyProfilePoint:
    knowledge_point: str
    mastery: float | None
    attempts: int
    correct: int


def _get_subject(session: Session, subject: str) -> Subject | None:
    return session.exec(select(Subject).where(Subject.slug == subject)).first()


def _get_user(session: Session, user_id: str) -> User | None:
    return session.exec(select(User).where(User.username == user_id)).first()


def _resolve_target_name(
    session: Session,
    *,
    granularity: str,
    target_id: int,
) -> str:
    if granularity == "unit":
        unit = session.get(TeachingUnit, target_id)
        return unit.canonical_name if unit is not None else f"unit#{target_id}"
    node = session.get(KnowledgeNode, target_id)
    return node.canonical_name if node is not None else f"node#{target_id}"


def list_knowledge_states(session: Session, *, user_id: str, subject: str) -> list[UserKnowledgeState]:
    subject_record = _get_subject(session, subject)
    user = _get_user(session, user_id)
    if subject_record is None or user is None or subject_record.id is None or user.id is None:
        return []
    return list(
        session.exec(
            select(UserKnowledgeState)
            .where(
                UserKnowledgeState.user_id == user.id,
                UserKnowledgeState.subject_id == subject_record.id,
            )
            .order_by(UserKnowledgeState.review_priority.desc(), UserKnowledgeState.updated_at.desc())  # type: ignore[union-attr]
        ).all()
    )


def get_knowledge_state(
    session: Session,
    *,
    user_id: str,
    subject: str,
    granularity: str,
    target_id: int,
) -> UserKnowledgeState | None:
    subject_record = _get_subject(session, subject)
    user = _get_user(session, user_id)
    if subject_record is None or user is None or subject_record.id is None or user.id is None:
        return None
    return session.exec(
        select(UserKnowledgeState).where(
            UserKnowledgeState.user_id == user.id,
            UserKnowledgeState.subject_id == subject_record.id,
            UserKnowledgeState.granularity == granularity,
            UserKnowledgeState.target_id == target_id,
        )
    ).first()


def list_pending_reviews(session: Session, *, user_id: str, subject: str) -> list[ReviewTask]:
    subject_record = _get_subject(session, subject)
    user = _get_user(session, user_id)
    if subject_record is None or user is None or subject_record.id is None or user.id is None:
        return []
    return list(
        session.exec(
            select(ReviewTask)
            .where(
                ReviewTask.user_id == user.id,
                ReviewTask.subject_id == subject_record.id,
                ReviewTask.status == "pending",
            )
            .order_by(ReviewTask.priority.desc(), ReviewTask.scheduled_at.asc())  # type: ignore[union-attr]
        ).all()
    )


def complete_review_task(
    session: Session,
    *,
    task_id: int,
    user_id: str,
    subject: str,
) -> ReviewTask | None:
    task = session.get(ReviewTask, task_id)
    subject_record = _get_subject(session, subject)
    user = _get_user(session, user_id)
    if (
        task is None
        or subject_record is None
        or user is None
        or task.subject_id != subject_record.id
        or task.user_id != user.id
    ):
        return None
    task.status = "completed"
    task.completed_at = utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def list_weak_node_summaries(
    session: Session,
    *,
    user_id: str,
    subject: str,
    limit: int,
) -> list[tuple[str, float]]:
    states = [
        item
        for item in list_knowledge_states(session, user_id=user_id, subject=subject)
        if item.granularity == "node"
    ]
    states.sort(key=lambda item: (item.mastery_score, -item.review_priority))
    return [
        (_resolve_target_name(session, granularity="node", target_id=item.target_id), item.mastery_score)
        for item in states[:limit]
    ]


def list_recent_wrong_attempt_summaries(
    session: Session,
    *,
    user_id: str,
    subject: str,
    limit: int,
) -> list[dict[str, object]]:
    subject_record = _get_subject(session, subject)
    user = _get_user(session, user_id)
    if subject_record is None or user is None or subject_record.id is None or user.id is None:
        return []

    attempts = list(
        session.exec(
            select(UserAnswerAttempt)
            .where(
                UserAnswerAttempt.user_id == user.id,
                UserAnswerAttempt.is_correct.is_(False),
            )
            .order_by(UserAnswerAttempt.created_at.desc())  # type: ignore[union-attr]
        ).all()
    )
    results: list[dict[str, object]] = []
    for attempt in attempts:
        item = session.get(ExamPaperItem, attempt.exam_paper_item_id)
        if item is None:
            continue
        paper = session.get(ExamPaper, item.exam_paper_id)
        if paper is None or paper.subject_id != subject_record.id:
            continue
        results.append(
            {
                "question_stem": item.snapshot_stem,
                "user_answer": attempt.user_answer,
                "correct_answer": item.snapshot_answer,
                "analysis": item.snapshot_explanation,
                "knowledge_point": _resolve_target_name(
                    session,
                    granularity="unit",
                    target_id=item.snapshot_teaching_unit_id,
                ),
                "created_at": attempt.created_at,
                "question_type": item.snapshot_question_type,
            }
        )
        if len(results) >= limit:
            break
    return results


def get_weak_points(session: Session, subject: str, limit: int = 10) -> list[LegacyProfilePoint]:
    states = [
        item
        for item in list_knowledge_states(session, user_id="local", subject=subject)
        if item.granularity == "node"
    ]
    states.sort(key=lambda item: (item.mastery_score, -item.review_priority))
    return [
        LegacyProfilePoint(
            knowledge_point=_resolve_target_name(session, granularity="node", target_id=item.target_id),
            mastery=item.mastery_score,
            attempts=item.total_attempts,
            correct=item.correct_attempts,
        )
        for item in states[:limit]
    ]


def list_profiles_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int,
    offset: int,
) -> tuple[list[LegacyProfilePoint], int]:
    states = list_knowledge_states(session, user_id="local", subject=subject)
    items = [
        LegacyProfilePoint(
            knowledge_point=_resolve_target_name(
                session,
                granularity=item.granularity,
                target_id=item.target_id,
            ),
            mastery=item.mastery_score,
            attempts=item.total_attempts,
            correct=item.correct_attempts,
        )
        for item in states
    ]
    total = len(items)
    return items[offset : offset + limit], total


__all__ = [
    "LegacyProfilePoint",
    "complete_review_task",
    "get_knowledge_state",
    "get_weak_points",
    "list_knowledge_states",
    "list_pending_reviews",
    "list_profiles_by_subject",
    "list_recent_wrong_attempt_summaries",
    "list_weak_node_summaries",
]
