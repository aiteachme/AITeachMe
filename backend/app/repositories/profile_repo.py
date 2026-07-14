"""Profile and mastery data access layer."""

from __future__ import annotations

import json
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Session, select

from app.models import ExamPaper, ExamPaperItem, KnowledgeUnit, QuestionKnowledgeUnitLink, UserKnowledgeState
from app.shared.infra.database import is_postgres
from app.utils.time import utcnow


def _validate_target_ref(*, knowledge_unit_id: int | None = None) -> int:
    if knowledge_unit_id is not None:
        return knowledge_unit_id
    raise ValueError("knowledge_unit_id must be provided.")


def _apply_state_target_filter(
    stmt,
    *,
    knowledge_unit_id: int | None = None,
    target_kind: str | None = None,
):
    if knowledge_unit_id is not None:
        return stmt.where(UserKnowledgeState.knowledge_unit_id == knowledge_unit_id)
    if target_kind == "knowledge_unit":
        return stmt.where(UserKnowledgeState.knowledge_unit_id.is_not(None))
    return stmt


def compare_and_set_knowledge_state(
    session: Session,
    state: UserKnowledgeState,
    *,
    expected_state_version: int | None,
    auto_commit: bool = True,
) -> UserKnowledgeState | None:
    """Persist a mastery state only when its previously read version still matches."""

    now = utcnow()
    target_ref_id = _validate_target_ref(knowledge_unit_id=state.knowledge_unit_id)
    expected_next_version = 1 if expected_state_version is None else expected_state_version + 1
    if state.state_version != expected_next_version:
        raise ValueError(
            "UserKnowledgeState state_version must advance exactly once "
            f"({state.state_version} != {expected_next_version})."
        )
    insert_values = {
        "user_id": state.user_id,
        "course_id": state.course_id,
        "knowledge_unit_id": state.knowledge_unit_id,
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

    update_values = {
        key: value
        for key, value in insert_values.items()
        if key not in {"user_id", "course_id", "knowledge_unit_id"}
    }

    conflict_columns = ["user_id", "course_id", "knowledge_unit_id"]
    conflict_where = "knowledge_unit_id IS NOT NULL"

    if expected_state_version is None:
        if is_postgres():
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            stmt = pg_insert(UserKnowledgeState).values(**insert_values)
        else:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            stmt = sqlite_insert(UserKnowledgeState).values(**insert_values)
        stmt = stmt.on_conflict_do_nothing(
            index_elements=conflict_columns,
            index_where=sa.text(conflict_where),
        )
    else:
        stmt = (
            sa.update(UserKnowledgeState)
            .where(
                UserKnowledgeState.user_id == state.user_id,
                UserKnowledgeState.course_id == state.course_id,
                UserKnowledgeState.knowledge_unit_id == state.knowledge_unit_id,
                UserKnowledgeState.state_version == expected_state_version,
            )
            .values(**update_values)
            .execution_options(synchronize_session=False)
        )

    result = session.exec(stmt)
    if int(getattr(result, "rowcount", 0) or 0) != 1:
        session.expire_all()
        return None

    if auto_commit:
        session.commit()
    else:
        session.flush()
    session.expire_all()
    persisted = get_knowledge_state(
        session,
        user_id=state.user_id,
        course_id=state.course_id,
        knowledge_unit_id=target_ref_id,
    )
    if persisted is None:
        raise ValueError("UserKnowledgeState compare-and-set failed after a successful write.")
    return persisted


def get_knowledge_state(
    session: Session,
    *,
    user_id: str,
    course_id: str,
    knowledge_unit_id: int | None = None,
) -> UserKnowledgeState | None:
    stmt = select(UserKnowledgeState).where(
        UserKnowledgeState.user_id == user_id,
        UserKnowledgeState.course_id == course_id,
    )
    stmt = _apply_state_target_filter(
        stmt,
        knowledge_unit_id=knowledge_unit_id,
    )
    return session.exec(stmt).first()


def list_knowledge_states(
    session: Session,
    *,
    user_id: str,
    course_id: str,
    target_kind: str | None = None,
) -> list[UserKnowledgeState]:
    stmt = select(UserKnowledgeState).where(
        UserKnowledgeState.user_id == user_id,
        UserKnowledgeState.course_id == course_id,
    )
    stmt = _apply_state_target_filter(stmt, target_kind=target_kind)
    return list(session.exec(stmt.order_by(UserKnowledgeState.updated_at.desc())).all())


def list_weak_knowledge_states(
    session: Session,
    *,
    user_id: str,
    course_id: str,
    threshold: float = 0.8,
    target_kind: str | None = None,
) -> list[UserKnowledgeState]:
    stmt = (
        select(UserKnowledgeState)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.course_id == course_id,
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
    course_id: str,
    as_of: datetime,
    target_kind: str | None = None,
) -> list[UserKnowledgeState]:
    stmt = (
        select(UserKnowledgeState)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.course_id == course_id,
            UserKnowledgeState.forgetting_due_at.is_not(None),
            UserKnowledgeState.forgetting_due_at <= as_of,
        )
        .order_by(UserKnowledgeState.forgetting_due_at.asc())
    )
    stmt = _apply_state_target_filter(stmt, target_kind=target_kind)
    return list(session.exec(stmt).all())


def list_weak_knowledge_unit_summaries(
    session: Session,
    *,
    user_id: str,
    course_id: str,
    threshold: float = 0.8,
    limit: int = 10,
) -> list[tuple[str, float]]:
    stmt = (
        select(KnowledgeUnit.canonical_name, UserKnowledgeState.mastery_score)
        .join(KnowledgeUnit, UserKnowledgeState.knowledge_unit_id == KnowledgeUnit.id)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.course_id == course_id,
            UserKnowledgeState.knowledge_unit_id.is_not(None),
            UserKnowledgeState.mastery_score < threshold,
            KnowledgeUnit.course_id == course_id,
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
    course_id: str,
    knowledge_unit_ids: list[int] | None = None,
    limit: int = 5,
) -> list[dict[str, str]]:
    candidate_limit = max(limit, 1)
    target_knowledge_unit_ids = {
        int(knowledge_unit_id)
        for knowledge_unit_id in (knowledge_unit_ids or [])
        if int(knowledge_unit_id) > 0
    }
    if target_knowledge_unit_ids:
        candidate_limit = max(candidate_limit * 8, 20)

    stmt = (
        select(
            ExamPaperItem.stem_snapshot,
            ExamPaperItem.answer_content,
            ExamPaperItem.answer_snapshot,
            ExamPaperItem.error_cause_label,
            ExamPaperItem.explanation_snapshot,
            ExamPaperItem.id,
        )
        .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
        .where(
            ExamPaper.user_id == user_id,
            ExamPaper.course_id == course_id,
            ExamPaperItem.is_correct.is_(False),
        )
        .order_by(ExamPaperItem.answered_at.desc(), ExamPaperItem.id.desc())
        .limit(candidate_limit)
    )
    rows = session.exec(stmt).all()

    ordered_rows = list(rows)
    if target_knowledge_unit_ids:
        item_ids = [int(row[5]) for row in rows if row[5] is not None]
        link_rows = list(
            session.exec(
                select(QuestionKnowledgeUnitLink.exam_paper_item_id, QuestionKnowledgeUnitLink.knowledge_unit_id)
                .where(QuestionKnowledgeUnitLink.exam_paper_item_id.in_(item_ids))
            ).all()
        )
        unit_ids_by_item_id: dict[int, set[int]] = {}
        for item_id, unit_id in link_rows:
            if item_id is None:
                continue
            unit_ids_by_item_id.setdefault(int(item_id), set()).add(int(unit_id))
        overlapping_rows: list[tuple[str, str, str, str | None, str | None, int]] = []
        other_rows: list[tuple[str, str, str, str | None, str | None, int]] = []
        for row in rows:
            if unit_ids_by_item_id.get(int(row[5]), set()) & target_knowledge_unit_ids:
                overlapping_rows.append(row)
                continue
            other_rows.append(row)
        ordered_rows = overlapping_rows + other_rows

    items: list[dict[str, str]] = []
    for stem, answer_content, correct_answer, error_label, explanation, _item_id in ordered_rows[:limit]:
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
    course_id: str,
    knowledge_unit_id: int | None = None,
) -> UserKnowledgeState | None:
    _validate_target_ref(knowledge_unit_id=knowledge_unit_id)
    stmt = select(UserKnowledgeState).where(
        UserKnowledgeState.user_id == user_id,
        UserKnowledgeState.course_id == course_id,
        UserKnowledgeState.review_status == "pending",
    )
    stmt = _apply_state_target_filter(
        stmt,
        knowledge_unit_id=knowledge_unit_id,
    )
    return session.exec(stmt).first()


def list_pending_reviews(
    session: Session,
    *,
    user_id: str,
    course_id: str,
    target_kind: str | None = None,
) -> list[UserKnowledgeState]:
    stmt = (
        select(UserKnowledgeState)
        .where(
            UserKnowledgeState.user_id == user_id,
            UserKnowledgeState.course_id == course_id,
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
    course_id: str,
    auto_commit: bool = True,
) -> UserKnowledgeState | None:
    stmt = select(UserKnowledgeState).where(
        UserKnowledgeState.id == task_id,
        UserKnowledgeState.user_id == user_id,
        UserKnowledgeState.course_id == course_id,
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
