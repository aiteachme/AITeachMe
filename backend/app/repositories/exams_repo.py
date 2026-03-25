"""Exam-oriented repository helpers backed by the new schema."""

from __future__ import annotations

from sqlmodel import Session, select

from app.models import ExamPaper, ExamPaperItem, Subject, User, UserAnswerAttempt


def _get_subject(session: Session, subject: str) -> Subject | None:
    return session.exec(select(Subject).where(Subject.slug == subject)).first()


def _get_user(session: Session, user_id: str) -> User | None:
    return session.exec(select(User).where(User.username == user_id)).first()


def list_mistakes_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int,
    offset: int,
    user_id: str = "local",
) -> tuple[list[dict[str, object]], int]:
    subject_record = _get_subject(session, subject)
    user = _get_user(session, user_id)
    if subject_record is None or user is None or subject_record.id is None or user.id is None:
        return [], 0

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
    items: list[dict[str, object]] = []
    for attempt in attempts:
        exam_item = session.get(ExamPaperItem, attempt.exam_paper_item_id)
        if exam_item is None:
            continue
        exam_paper = session.get(ExamPaper, exam_item.exam_paper_id)
        if exam_paper is None or exam_paper.subject_id != subject_record.id:
            continue
        items.append(
            {
                "id": int(attempt.id or 0),
                "question_stem": exam_item.snapshot_stem,
                "question_type": exam_item.snapshot_question_type,
                "user_answer": attempt.user_answer,
                "correct_answer": exam_item.snapshot_answer,
                "analysis": exam_item.snapshot_explanation,
                "knowledge_point": str(exam_item.snapshot_teaching_unit_id),
                "created_at": attempt.created_at,
            }
        )
    total = len(items)
    return items[offset : offset + limit], total


__all__ = ["list_mistakes_by_subject"]
