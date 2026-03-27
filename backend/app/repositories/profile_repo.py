"""Profile and mastery data access layer."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from app.models import ExamPaper, ExamPaperItem, KnowledgeNode, ReviewTask, UserAnswerAttempt, UserKnowledgeState
from app.utils.time import utcnow


def _validate_target_ref(
    *,
    teaching_unit_id: int | None = None,
    knowledge_node_id: int | None = None,
) -> tuple[str, int]:
    if teaching_unit_id is not None and knowledge_node_id is None:
        return "unit", teaching_unit_id
    if teaching_unit_id is None and knowledge_node_id is not None:
        return "node", knowledge_node_id
    raise ValueError("Exactly one target ref must be provided.")


def _apply_state_target_filter(
    stmt,
    *,
    teaching_unit_id: int | None = None,
    knowledge_node_id: int | None = None,
    target_kind: str | None = None,
):
    if teaching_unit_id is not None:
        return stmt.where(
            UserKnowledgeState.teaching_unit_id == teaching_unit_id,
            UserKnowledgeState.knowledge_node_id.is_(None),
        )
    if knowledge_node_id is not None:
        return stmt.where(
            UserKnowledgeState.knowledge_node_id == knowledge_node_id,
            UserKnowledgeState.teaching_unit_id.is_(None),
        )
    if target_kind == "unit":
        return stmt.where(
            UserKnowledgeState.teaching_unit_id.is_not(None),
            UserKnowledgeState.knowledge_node_id.is_(None),
        )
    if target_kind == "node":
        return stmt.where(
            UserKnowledgeState.knowledge_node_id.is_not(None),
            UserKnowledgeState.teaching_unit_id.is_(None),
        )
    return stmt


def _apply_review_target_filter(
    stmt,
    *,
    teaching_unit_id: int | None = None,
    knowledge_node_id: int | None = None,
    target_kind: str | None = None,
):
    if teaching_unit_id is not None:
        return stmt.where(
            ReviewTask.teaching_unit_id == teaching_unit_id,
            ReviewTask.knowledge_node_id.is_(None),
        )
    if knowledge_node_id is not None:
        return stmt.where(
            ReviewTask.knowledge_node_id == knowledge_node_id,
            ReviewTask.teaching_unit_id.is_(None),
        )
    if target_kind == "unit":
        return stmt.where(
            ReviewTask.teaching_unit_id.is_not(None),
            ReviewTask.knowledge_node_id.is_(None),
        )
    if target_kind == "node":
        return stmt.where(
            ReviewTask.knowledge_node_id.is_not(None),
            ReviewTask.teaching_unit_id.is_(None),
        )
    return stmt


def upsert_knowledge_state(session: Session, state: UserKnowledgeState) -> UserKnowledgeState:
    now = utcnow()
    target_kind, target_ref_id = _validate_target_ref(
        teaching_unit_id=state.teaching_unit_id,
        knowledge_node_id=state.knowledge_node_id,
    )
    insert_values = {
        "user_id": state.user_id,
        "subject": state.subject,
        "teaching_unit_id": state.teaching_unit_id,
        "knowledge_node_id": state.knowledge_node_id,
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
        "stats_json": state.stats_json,
        "updated_at": now,
    }

    stmt = sqlite_insert(UserKnowledgeState).values(**insert_values)
    if target_kind == "unit":
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "subject", "teaching_unit_id"],
            index_where=sa.text("knowledge_node_id IS NULL"),
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
                "stats_json": insert_values["stats_json"],
                "updated_at": insert_values["updated_at"],
            },
        )
    else:
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "subject", "knowledge_node_id"],
            index_where=sa.text("teaching_unit_id IS NULL"),
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
                "stats_json": insert_values["stats_json"],
                "updated_at": insert_values["updated_at"],
            },
        )

    session.exec(stmt)
    session.commit()
    persisted = get_knowledge_state(
        session,
        user_id=state.user_id,
        subject=state.subject,
        teaching_unit_id=(target_ref_id if target_kind == "unit" else None),
        knowledge_node_id=(target_ref_id if target_kind == "node" else None),
    )
    if persisted is None:
        raise ValueError("UserKnowledgeState upsert failed.")
    return persisted


def get_knowledge_state(
    session: Session,
    *,
    user_id: str,
    subject: str,
    teaching_unit_id: int | None = None,
    knowledge_node_id: int | None = None,
) -> UserKnowledgeState | None:
    stmt = select(UserKnowledgeState).where(
        UserKnowledgeState.user_id == user_id,
        UserKnowledgeState.subject == subject,
    )
    stmt = _apply_state_target_filter(
        stmt,
        teaching_unit_id=teaching_unit_id,
        knowledge_node_id=knowledge_node_id,
    )
    return session.exec(stmt).first()


def list_knowledge_states(
    session: Session,
    *,
    user_id: str,
    subject: str,
    target_kind: str | None = None,
) -> list[UserKnowledgeState]:
    stmt = select(UserKnowledgeState).where(
        UserKnowledgeState.user_id == user_id,
        UserKnowledgeState.subject == subject,
    )
    stmt = _apply_state_target_filter(stmt, target_kind=target_kind)
    return list(session.exec(stmt.order_by(UserKnowledgeState.updated_at.desc())).all())


def list_weak_knowledge_states(
    session: Session,
    *,
    user_id: str,
    subject: str,
    threshold: float = 0.8,
    target_kind: str | None = None,
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
    stmt = _apply_state_target_filter(stmt, target_kind=target_kind)
    return list(session.exec(stmt).all())


def list_due_knowledge_states(
    session: Session,
    *,
    user_id: str,
    subject: str,
    as_of: datetime,
    target_kind: str | None = None,
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
    stmt = _apply_state_target_filter(stmt, target_kind=target_kind)
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
        .join(KnowledgeNode, UserKnowledgeState.knowledge_node_id == KnowledgeNode.id)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject == subject,
            UserKnowledgeState.knowledge_node_id.is_not(None),
            UserKnowledgeState.teaching_unit_id.is_(None),
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
            ExamPaperItem.stem_snapshot,
            UserAnswerAttempt.answer_content,
            ExamPaperItem.answer_snapshot,
            UserAnswerAttempt.error_cause_label,
            ExamPaperItem.explanation_snapshot,
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
    for stem, answer_content, correct_answer, error_label, explanation in rows:
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
                "user_answer": str(answer_content or ""),
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
            teaching_unit_id=task.teaching_unit_id,
            knowledge_node_id=task.knowledge_node_id,
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
    teaching_unit_id: int | None = None,
    knowledge_node_id: int | None = None,
) -> ReviewTask | None:
    _validate_target_ref(
        teaching_unit_id=teaching_unit_id,
        knowledge_node_id=knowledge_node_id,
    )
    stmt = select(ReviewTask).where(
        ReviewTask.user_id == user_id,
        ReviewTask.subject == subject,
        ReviewTask.status == "pending",
    )
    stmt = _apply_review_target_filter(
        stmt,
        teaching_unit_id=teaching_unit_id,
        knowledge_node_id=knowledge_node_id,
    )
    return session.exec(stmt).first()


def list_pending_reviews(
    session: Session,
    *,
    user_id: str,
    subject: str,
    target_kind: str | None = None,
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
    stmt = _apply_review_target_filter(stmt, target_kind=target_kind)
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
