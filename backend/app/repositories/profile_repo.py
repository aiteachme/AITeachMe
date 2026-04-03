"""Profile and mastery data access layer."""

from __future__ import annotations

import json
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from app.models import ExamPaper, ExamPaperItem, KnowledgeNode, UserKnowledgeState
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


def upsert_knowledge_state(
    session: Session,
    state: UserKnowledgeState,
    *,
    auto_commit: bool = True,
) -> UserKnowledgeState:
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
        "review_status": state.review_status,
        "scheduled_review_at": state.scheduled_review_at,
        "review_interval_days": state.review_interval_days,
        "review_ease_factor": state.review_ease_factor,
        "review_repetition_count": state.review_repetition_count,
        "review_reason": state.review_reason,
        "source_exam_paper_id": state.source_exam_paper_id,
        "state_version": state.state_version,
        "last_recomputed_at": state.last_recomputed_at,
        "stats_json": state.stats_json,
        "updated_at": now,
    }

    stmt = sqlite_insert(UserKnowledgeState).values(**insert_values)
    set_values = {
        key: value
        for key, value in insert_values.items()
        if key not in {"user_id", "subject", "teaching_unit_id", "knowledge_node_id"}
    }
    if target_kind == "unit":
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "subject", "teaching_unit_id"],
            index_where=sa.text("knowledge_node_id IS NULL"),
            set_=set_values,
        )
    else:
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "subject", "knowledge_node_id"],
            index_where=sa.text("teaching_unit_id IS NULL"),
            set_=set_values,
        )

    session.exec(stmt)
    if auto_commit:
        session.commit()
    else:
        session.flush()
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


def _extract_node_ids_from_refs(node_refs_json: str | None) -> set[int]:
    if not node_refs_json:
        return set()
    try:
        payload = json.loads(node_refs_json)
    except json.JSONDecodeError:
        return set()
    if not isinstance(payload, list):
        return set()
    return {
        int(raw_node_id)
        for row in payload
        if isinstance(row, dict)
        for raw_node_id in [row.get("knowledge_node_id")]
        if isinstance(raw_node_id, int) and raw_node_id > 0
    }


def list_recent_wrong_attempt_summaries(
    session: Session,
    *,
    user_id: str,
    subject: str,
    teaching_unit_id: int | None = None,
    knowledge_node_ids: list[int] | None = None,
    limit: int = 5,
) -> list[dict[str, str]]:
    candidate_limit = max(limit, 1)
    target_node_ids = {
        int(node_id)
        for node_id in (knowledge_node_ids or [])
        if int(node_id) > 0
    }
    if teaching_unit_id is not None or target_node_ids:
        candidate_limit = max(candidate_limit * 8, 20)

    stmt = (
        select(
            ExamPaperItem.stem_snapshot,
            ExamPaperItem.answer_content,
            ExamPaperItem.answer_snapshot,
            ExamPaperItem.error_cause_label,
            ExamPaperItem.explanation_snapshot,
            ExamPaperItem.node_refs_json,
        )
        .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
        .where(
            ExamPaper.user_id == user_id,
            ExamPaper.subject == subject,
            ExamPaperItem.is_correct.is_(False),
        )
        .order_by(ExamPaperItem.answered_at.desc(), ExamPaperItem.id.desc())
        .limit(candidate_limit)
    )
    if teaching_unit_id is not None:
        stmt = stmt.where(ExamPaperItem.teaching_unit_id == teaching_unit_id)
    rows = session.exec(stmt).all()

    ordered_rows = list(rows)
    if target_node_ids:
        overlapping_rows: list[tuple[str, str, str, str | None, str | None, str]] = []
        other_rows: list[tuple[str, str, str, str | None, str | None, str]] = []
        for row in rows:
            if _extract_node_ids_from_refs(row[5]) & target_node_ids:
                overlapping_rows.append(row)
                continue
            other_rows.append(row)
        ordered_rows = overlapping_rows + other_rows

    items: list[dict[str, str]] = []
    for stem, answer_content, correct_answer, error_label, explanation, _node_refs_json in ordered_rows[:limit]:
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


def find_pending_review(
    session: Session,
    *,
    user_id: str,
    subject: str,
    teaching_unit_id: int | None = None,
    knowledge_node_id: int | None = None,
) -> UserKnowledgeState | None:
    _validate_target_ref(
        teaching_unit_id=teaching_unit_id,
        knowledge_node_id=knowledge_node_id,
    )
    stmt = select(UserKnowledgeState).where(
        UserKnowledgeState.user_id == user_id,
        UserKnowledgeState.subject == subject,
        UserKnowledgeState.review_status == "pending",
    )
    stmt = _apply_state_target_filter(
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
) -> list[UserKnowledgeState]:
    stmt = (
        select(UserKnowledgeState)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.subject == subject,
            UserKnowledgeState.review_status == "pending",
        )
        .order_by(
            UserKnowledgeState.review_priority.desc(),
            UserKnowledgeState.scheduled_review_at.asc(),
            UserKnowledgeState.id.asc(),
        )
    )
    stmt = _apply_state_target_filter(stmt, target_kind=target_kind)
    return list(session.exec(stmt).all())


def complete_review_task(
    session: Session,
    *,
    task_id: int,
    user_id: str,
    subject: str,
    auto_commit: bool = True,
) -> UserKnowledgeState | None:
    stmt = select(UserKnowledgeState).where(
        UserKnowledgeState.id == task_id,
        UserKnowledgeState.user_id == user_id,
        UserKnowledgeState.subject == subject,
    )
    state = session.exec(stmt).first()
    if state is None:
        return None

    state.review_status = "completed"
    state.scheduled_review_at = None
    state.review_reason = None
    state.updated_at = utcnow()
    session.add(state)
    if auto_commit:
        session.commit()
        session.refresh(state)
    else:
        session.flush()
    return state
