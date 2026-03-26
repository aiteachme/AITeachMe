"""Profile and mastery data access layer."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from app.models import ExamPaper, ExamPaperItem, KnowledgeNode, ReviewTask, UserAnswerAttempt, UserKnowledgeState
from app.utils.time import utcnow


def upsert_knowledge_state(session: Session, state: UserKnowledgeState) -> UserKnowledgeState:
    now = utcnow()
    insert_values = {
        "user_id": state.user_id,
        "subject": state.subject,
        "granularity": state.granularity,
        "target_id": state.target_id,
        "mastery_score": state.mastery_score,
        "confidence_score": state.confidence_score,
        "stability_score": state.stability_score,
        "forgetting_due_at": state.forgetting_due_at,
        "review_priority": state.review_priority,
        "total_attempts": state.total_attempts,
        "correct_attempts": state.correct_attempts,
        "last_attempt_at": state.last_attempt_at,
        "state_version": state.state_version,
        "last_recomputed_at": state.last_recomputed_at,
        "updated_at": now,
    }

    stmt = sqlite_insert(UserKnowledgeState).values(**insert_values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["user_id", "subject", "granularity", "target_id"],
        set_={
            "mastery_score": insert_values["mastery_score"],
            "confidence_score": insert_values["confidence_score"],
            "stability_score": insert_values["stability_score"],
            "forgetting_due_at": insert_values["forgetting_due_at"],
            "review_priority": insert_values["review_priority"],
            "total_attempts": insert_values["total_attempts"],
            "correct_attempts": insert_values["correct_attempts"],
            "last_attempt_at": insert_values["last_attempt_at"],
            "state_version": insert_values["state_version"],
            "last_recomputed_at": insert_values["last_recomputed_at"],
            "updated_at": insert_values["updated_at"],
        },
    )

    session.exec(stmt)
    session.commit()
    persisted = get_knowledge_state(
        session,
        user_id=state.user_id,
        subject=state.subject,
        granularity=state.granularity,
        target_id=state.target_id,
    )
    if persisted is None:
        raise ValueError("UserKnowledgeState upsert failed.")
    return persisted


def get_knowledge_state(
    session: Session,
    *,
    user_id: str,
    subject: str,
    granularity: str,
    target_id: int,
) -> UserKnowledgeState | None:
    stmt = select(UserKnowledgeState).where(
        UserKnowledgeState.user_id == user_id,
        UserKnowledgeState.subject == subject,
        UserKnowledgeState.granularity == granularity,
        UserKnowledgeState.target_id == target_id,
    )
    return session.exec(stmt).first()


def list_knowledge_states(
    session: Session,
    *,
    user_id: str,
    subject: str,
    granularity: str | None = None,
) -> list[UserKnowledgeState]:
    stmt = select(UserKnowledgeState).where(
        UserKnowledgeState.user_id == user_id,
        UserKnowledgeState.subject == subject,
    )
    if granularity is not None:
        stmt = stmt.where(UserKnowledgeState.granularity == granularity)
    return list(session.exec(stmt.order_by(UserKnowledgeState.updated_at.desc())).all())


def list_weak_knowledge_states(
    session: Session,
    *,
    user_id: str,
    subject: str,
    threshold: float = 0.8,
) -> list[UserKnowledgeState]:
    stmt = (
        select(UserKnowledgeState)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject == subject,
            UserKnowledgeState.mastery_score < threshold,
        )
        .order_by(UserKnowledgeState.mastery_score.asc())
    )
    return list(session.exec(stmt).all())


def list_due_knowledge_states(
    session: Session,
    *,
    user_id: str,
    subject: str,
    as_of: datetime,
) -> list[UserKnowledgeState]:
    stmt = (
        select(UserKnowledgeState)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject == subject,
            UserKnowledgeState.forgetting_due_at.is_not(None),
            UserKnowledgeState.forgetting_due_at <= as_of,
        )
        .order_by(UserKnowledgeState.forgetting_due_at.asc())
    )
    return list(session.exec(stmt).all())


def list_weak_node_summaries(
    session: Session,
    *,
    user_id: str,
    subject: str,
    threshold: float = 0.8,
    limit: int = 10,
) -> list[tuple[str, float]]:
    stmt = (
        select(KnowledgeNode.canonical_name, UserKnowledgeState.mastery_score)
        .join(KnowledgeNode, UserKnowledgeState.target_id == KnowledgeNode.id)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject == subject,
            UserKnowledgeState.granularity == "node",
            UserKnowledgeState.mastery_score < threshold,
            KnowledgeNode.subject == subject,
        )
        .order_by(
            UserKnowledgeState.mastery_score.asc(),
            UserKnowledgeState.updated_at.desc(),
        )
        .limit(limit)
    )
    return [
        (str(name), float(mastery))
        for name, mastery in session.exec(stmt).all()
        if name is not None and mastery is not None
    ]


def list_recent_wrong_attempt_summaries(
    session: Session,
    *,
    user_id: str,
    subject: str,
    limit: int = 5,
) -> list[dict[str, str]]:
    stmt = (
        select(
            ExamPaperItem.snapshot_stem,
            UserAnswerAttempt.user_answer,
            ExamPaperItem.snapshot_answer,
            UserAnswerAttempt.error_cause_label,
            ExamPaperItem.snapshot_explanation,
        )
        .join(ExamPaperItem, UserAnswerAttempt.exam_paper_item_id == ExamPaperItem.id)
        .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
        .where(
            ExamPaper.user_id == user_id,
            ExamPaper.subject == subject,
            UserAnswerAttempt.is_correct.is_(False),
        )
        .order_by(UserAnswerAttempt.created_at.desc())
        .limit(limit)
    )
    rows = session.exec(stmt).all()
    items: list[dict[str, str]] = []
    for stem, user_answer, correct_answer, error_label, explanation in rows:
        analysis = ""
        if error_label and error_label != "unknown":
            analysis = f"Possible error cause: {error_label}"
        elif explanation:
            analysis = str(explanation).strip()
        if not analysis:
            analysis = "Please compare with standard answer and review key steps."
        items.append(
            {
                "question_stem": str(stem or ""),
                "user_answer": str(user_answer or ""),
                "correct_answer": str(correct_answer or ""),
                "analysis": analysis,
            }
        )
    return items


def upsert_review_task(session: Session, task: ReviewTask) -> ReviewTask:
    if task.status == "pending":
        existing = find_pending_review(
            session,
            user_id=task.user_id,
            subject=task.subject,
            target_id=task.target_id,
            target_granularity=task.target_granularity,
        )
        if existing is not None:
            existing.task_type = task.task_type
            existing.priority = task.priority
            existing.scheduled_at = task.scheduled_at
            existing.interval_days = task.interval_days
            existing.ease_factor = task.ease_factor
            existing.repetition_count = task.repetition_count
            existing.reason = task.reason
            existing.source_state_id = task.source_state_id
            existing.source_exam_paper_id = task.source_exam_paper_id
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing

    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def find_pending_review(
    session: Session,
    *,
    user_id: str,
    subject: str,
    target_id: int,
    target_granularity: str,
) -> ReviewTask | None:
    stmt = select(ReviewTask).where(
        ReviewTask.user_id == user_id,
        ReviewTask.subject == subject,
        ReviewTask.target_id == target_id,
        ReviewTask.target_granularity == target_granularity,
        ReviewTask.status == "pending",
    )
    return session.exec(stmt).first()


def list_pending_reviews(
    session: Session,
    *,
    user_id: str,
    subject: str,
) -> list[ReviewTask]:
    stmt = (
        select(ReviewTask)
        .where(
            ReviewTask.user_id == user_id,
            ReviewTask.subject == subject,
            ReviewTask.status == "pending",
        )
        .order_by(
            ReviewTask.priority.desc(),
            ReviewTask.scheduled_at.asc(),
            ReviewTask.id.asc(),
        )
    )
    return list(session.exec(stmt).all())


def complete_review_task(
    session: Session,
    *,
    task_id: int,
    user_id: str,
    subject: str,
) -> ReviewTask | None:
    stmt = select(ReviewTask).where(
        ReviewTask.id == task_id,
        ReviewTask.user_id == user_id,
        ReviewTask.subject == subject,
    )
    task = session.exec(stmt).first()
    if task is None:
        return None

    task.status = "completed"
    task.completed_at = utcnow()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task
