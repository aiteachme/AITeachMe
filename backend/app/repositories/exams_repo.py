"""Exam data access layer."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, func, select

from app.models import (
    CourseInitialExamJob,
    ExamPaper,
    ExamPaperItem,
    ExamProfileSync,
    ExamStudyGuideCache,
    MasteryDrillAttempt,
    MasteryDrillSession,
    QuestionKnowledgeUnitLink,
    QuestionTemplate,
    UserKnowledgeState,
)
from app.shared.kernel.question_types import require_supported_question_type_key
from app.utils.time import ensure_utc_datetime, utcnow


def create_question_template(session: Session, template: QuestionTemplate) -> QuestionTemplate:
    template.question_type = require_supported_question_type_key(template.question_type)
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


def set_question_template_mark(
    session: Session,
    *,
    course_id: str,
    template_id: int,
    is_marked: bool,
) -> QuestionTemplate | None:
    template = session.get(QuestionTemplate, template_id)
    if template is None or template.course_id != course_id:
        return None
    template.is_marked = is_marked
    template.updated_at = utcnow()
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


def list_marked_question_template_ids(session: Session, template_ids: list[int]) -> set[int]:
    ids = [int(item) for item in template_ids if int(item or 0) > 0]
    if not ids:
        return set()
    rows = session.exec(
        select(QuestionTemplate.id).where(
            QuestionTemplate.id.in_(ids),
            QuestionTemplate.is_marked == True,  # noqa: E712
        )
    ).all()
    return {int(item) for item in rows if item is not None}


def list_wrong_question_template_ids(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    template_ids: list[int],
) -> set[int]:
    ids = [int(item) for item in template_ids if int(item or 0) > 0]
    if not ids:
        return set()

    ranked = (
        select(
            ExamPaperItem.question_template_id.label("question_template_id"),
            ExamPaperItem.is_correct.label("is_correct"),
            func.row_number()
            .over(
                partition_by=ExamPaperItem.question_template_id,
                order_by=(ExamPaperItem.answered_at.desc(), ExamPaperItem.id.desc()),
            )
            .label("answer_rank"),
        )
        .join(ExamPaper, ExamPaper.id == ExamPaperItem.exam_paper_id)
        .where(
            ExamPaperItem.question_template_id.in_(ids),
            ExamPaperItem.answered_at.is_not(None),
            ExamPaper.course_id == course_id,
            ExamPaper.user_id == user_id,
            ExamPaper.visibility != "hidden",
            ExamPaper.exam_mode != "mastery_drill",
        )
        .subquery()
    )
    rows = session.exec(
        select(ranked.c.question_template_id).where(
            ranked.c.answer_rank == 1,
            ranked.c.is_correct.is_(False),
        )
    ).all()
    return {int(item) for item in rows if item is not None}


def list_question_template_answer_history(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    template_id: int,
    limit: int = 20,
) -> list[tuple[ExamPaperItem, ExamPaper]]:
    if template_id <= 0 or limit <= 0:
        return []
    stmt = (
        select(ExamPaperItem, ExamPaper)
        .join(ExamPaper, ExamPaper.id == ExamPaperItem.exam_paper_id)
        .where(
            ExamPaperItem.question_template_id == template_id,
            ExamPaperItem.answered_at.is_not(None),
            ExamPaper.course_id == course_id,
            ExamPaper.user_id == user_id,
            ExamPaper.visibility != "hidden",
            ExamPaper.exam_mode != "mastery_drill",
        )
        .order_by(ExamPaperItem.answered_at.desc(), ExamPaperItem.id.desc())
        .limit(limit)
    )
    return [(item, paper) for item, paper in session.exec(stmt).all()]


def _normalize_link_refs(refs: list[dict[str, object]]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    seen: set[int] = set()
    for ref in refs:
        try:
            unit_id = int(ref.get("knowledge_unit_id", 0) or 0)
        except (TypeError, ValueError):
            continue
        if unit_id <= 0 or unit_id in seen:
            continue
        seen.add(unit_id)
        try:
            weight = float(ref.get("coverage_weight", 1.0) or 1.0)
        except (TypeError, ValueError):
            weight = 1.0
        normalized.append(
            {
                "knowledge_unit_id": unit_id,
                "coverage_weight": max(0.0, min(weight, 1.0)),
            }
        )
    normalized.sort(key=lambda item: float(item["coverage_weight"]), reverse=True)
    return normalized


def _link_payload(link: QuestionKnowledgeUnitLink) -> dict[str, object]:
    return {
        "knowledge_unit_id": int(link.knowledge_unit_id),
        "coverage_weight": float(link.coverage_weight),
    }


def replace_question_template_links(
    session: Session,
    *,
    template_id: int,
    refs: list[dict[str, object]],
    auto_commit: bool = True,
) -> list[QuestionKnowledgeUnitLink]:
    session.exec(
        sa.delete(QuestionKnowledgeUnitLink).where(
            QuestionKnowledgeUnitLink.question_template_id == template_id
        )
    )
    links = [
        QuestionKnowledgeUnitLink(
            question_template_id=template_id,
            knowledge_unit_id=int(ref["knowledge_unit_id"]),
            coverage_weight=float(ref["coverage_weight"]),
        )
        for ref in _normalize_link_refs(refs)
    ]
    for link in links:
        session.add(link)
    if auto_commit:
        session.commit()
        for link in links:
            session.refresh(link)
    else:
        session.flush()
    return links


def replace_exam_paper_item_links(
    session: Session,
    *,
    item_id: int,
    refs: list[dict[str, object]],
    auto_commit: bool = True,
) -> list[QuestionKnowledgeUnitLink]:
    session.exec(
        sa.delete(QuestionKnowledgeUnitLink).where(
            QuestionKnowledgeUnitLink.exam_paper_item_id == item_id
        )
    )
    links = [
        QuestionKnowledgeUnitLink(
            exam_paper_item_id=item_id,
            knowledge_unit_id=int(ref["knowledge_unit_id"]),
            coverage_weight=float(ref["coverage_weight"]),
        )
        for ref in _normalize_link_refs(refs)
    ]
    for link in links:
        session.add(link)
    if auto_commit:
        session.commit()
        for link in links:
            session.refresh(link)
    else:
        session.flush()
    return links


def list_links_for_templates(session: Session, template_ids: list[int]) -> dict[int, list[dict[str, object]]]:
    ids = [int(item) for item in template_ids if int(item or 0) > 0]
    if not ids:
        return {}
    rows = list(
        session.exec(
            select(QuestionKnowledgeUnitLink)
            .where(QuestionKnowledgeUnitLink.question_template_id.in_(ids))
            .order_by(QuestionKnowledgeUnitLink.question_template_id.asc(), QuestionKnowledgeUnitLink.id.asc())
        ).all()
    )
    grouped: dict[int, list[dict[str, object]]] = {}
    for link in rows:
        if link.question_template_id is None:
            continue
        grouped.setdefault(int(link.question_template_id), []).append(_link_payload(link))
    return grouped


def list_links_for_exam_items(session: Session, item_ids: list[int]) -> dict[int, list[dict[str, object]]]:
    ids = [int(item) for item in item_ids if int(item or 0) > 0]
    if not ids:
        return {}
    rows = list(
        session.exec(
            select(QuestionKnowledgeUnitLink)
            .where(QuestionKnowledgeUnitLink.exam_paper_item_id.in_(ids))
            .order_by(QuestionKnowledgeUnitLink.exam_paper_item_id.asc(), QuestionKnowledgeUnitLink.id.asc())
        ).all()
    )
    grouped: dict[int, list[dict[str, object]]] = {}
    for link in rows:
        if link.exam_paper_item_id is None:
            continue
        grouped.setdefault(int(link.exam_paper_item_id), []).append(_link_payload(link))
    return grouped


def find_templates_by_unit(
    session: Session,
    unit_id: int,
    *,
    status: str = "active",
) -> list[QuestionTemplate]:
    stmt = select(QuestionTemplate).join(
        QuestionKnowledgeUnitLink,
        QuestionKnowledgeUnitLink.question_template_id == QuestionTemplate.id,
    ).where(QuestionKnowledgeUnitLink.knowledge_unit_id == unit_id)
    if status:
        stmt = stmt.where(QuestionTemplate.status == status)
    return list(session.exec(stmt.order_by(QuestionTemplate.id)).all())


def find_templates_by_node(
    session: Session,
    node_id: int,
    *,
    status: str = "active",
) -> list[QuestionTemplate]:
    stmt = select(QuestionTemplate).join(
        QuestionKnowledgeUnitLink,
        QuestionKnowledgeUnitLink.question_template_id == QuestionTemplate.id,
    ).where(QuestionKnowledgeUnitLink.knowledge_unit_id == node_id)
    if status:
        stmt = stmt.where(QuestionTemplate.status == status)
    return list(session.exec(stmt.order_by(QuestionTemplate.id)).all())


def find_template_by_stem_hash(
    session: Session,
    course_id: str,
    unit_id: int,
    stem_hash: str,
) -> QuestionTemplate | None:
    stmt = (
        select(QuestionTemplate)
        .join(
            QuestionKnowledgeUnitLink,
            QuestionKnowledgeUnitLink.question_template_id == QuestionTemplate.id,
        )
        .where(
            QuestionTemplate.course_id == course_id,
            QuestionTemplate.stem_hash == stem_hash,
            QuestionKnowledgeUnitLink.knowledge_unit_id == unit_id,
        )
        .order_by(QuestionTemplate.id.asc())
        .limit(1)
    )
    return session.exec(stmt).first()


def find_template_by_course_stem_hash(
    session: Session,
    course_id: str,
    stem_hash: str,
) -> QuestionTemplate | None:
    stmt = (
        select(QuestionTemplate)
        .where(
            QuestionTemplate.course_id == course_id,
            QuestionTemplate.stem_hash == stem_hash,
        )
        .order_by(QuestionTemplate.id.asc())
        .limit(1)
    )
    return session.exec(stmt).first()


def find_knowledge_unit_links_by_template(session: Session, template_id: int) -> list[dict[str, object]]:
    return list_links_for_templates(session, [template_id]).get(template_id, [])


def create_exam_paper(
    session: Session,
    paper: ExamPaper,
    *,
    auto_commit: bool = True,
) -> ExamPaper:
    session.add(paper)
    if auto_commit:
        session.commit()
        session.refresh(paper)
    else:
        session.flush()
    return paper


def create_exam_paper_items(
    session: Session,
    items: list[ExamPaperItem],
    *,
    auto_commit: bool = True,
) -> list[ExamPaperItem]:
    for item in items:
        item.question_type = require_supported_question_type_key(item.question_type)
        session.add(item)
    if auto_commit:
        session.commit()
        for item in items:
            session.refresh(item)
    else:
        session.flush()
    return items


def create_mastery_drill_session(
    session: Session,
    drill: MasteryDrillSession,
    *,
    auto_commit: bool = True,
) -> MasteryDrillSession:
    session.add(drill)
    if auto_commit:
        session.commit()
        session.refresh(drill)
    else:
        session.flush()
    return drill


def get_mastery_drill_session_by_paper(
    session: Session,
    *,
    paper_id: int,
) -> MasteryDrillSession | None:
    return session.exec(
        select(MasteryDrillSession).where(MasteryDrillSession.exam_paper_id == paper_id)
    ).first()


def get_mastery_drill_session_by_key(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    session_key: str,
) -> MasteryDrillSession | None:
    return session.exec(
        select(MasteryDrillSession).where(
            MasteryDrillSession.course_id == course_id,
            MasteryDrillSession.user_id == user_id,
            MasteryDrillSession.session_key == session_key,
        )
    ).first()


def get_open_mastery_drill_session(
    session: Session,
    *,
    course_id: str,
    user_id: str,
) -> MasteryDrillSession | None:
    """Return the active row even when its paper is no longer resumable."""

    return session.exec(
        select(MasteryDrillSession)
        .where(
            MasteryDrillSession.course_id == course_id,
            MasteryDrillSession.user_id == user_id,
            MasteryDrillSession.status == "active",
        )
        .order_by(MasteryDrillSession.updated_at.desc(), MasteryDrillSession.id.desc())
        .limit(1)
    ).first()


def get_active_mastery_drill_session(
    session: Session,
    *,
    course_id: str,
    user_id: str,
) -> MasteryDrillSession | None:
    return session.exec(
        select(MasteryDrillSession)
        .join(ExamPaper, ExamPaper.id == MasteryDrillSession.exam_paper_id)
        .where(
            MasteryDrillSession.course_id == course_id,
            MasteryDrillSession.user_id == user_id,
            MasteryDrillSession.status == "active",
            ExamPaper.status.in_(("ready", "in_progress")),
            ExamPaper.visibility != "hidden",
        )
        .order_by(MasteryDrillSession.updated_at.desc(), MasteryDrillSession.id.desc())
        .limit(1)
    ).first()


def list_mastery_drill_sessions_by_papers(
    session: Session,
    paper_ids: list[int],
) -> dict[int, MasteryDrillSession]:
    normalized_ids = sorted({int(paper_id) for paper_id in paper_ids if int(paper_id) > 0})
    if not normalized_ids:
        return {}
    rows = session.exec(
        select(MasteryDrillSession).where(MasteryDrillSession.exam_paper_id.in_(normalized_ids))
    ).all()
    return {int(row.exam_paper_id): row for row in rows}


def abandon_mastery_drill_session(
    session: Session,
    *,
    drill_session_id: int,
    abandoned_at: datetime,
) -> bool:
    result = session.exec(
        sa.update(MasteryDrillSession)
        .where(
            MasteryDrillSession.id == drill_session_id,
            MasteryDrillSession.status == "active",
        )
        .values(status="abandoned", updated_at=abandoned_at)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def list_mastery_drill_attempts(
    session: Session,
    *,
    drill_session_id: int,
) -> list[MasteryDrillAttempt]:
    return list(
        session.exec(
            select(MasteryDrillAttempt)
            .where(MasteryDrillAttempt.mastery_drill_session_id == drill_session_id)
            .order_by(MasteryDrillAttempt.created_at.asc(), MasteryDrillAttempt.id.asc())
        ).all()
    )


def list_mastery_drill_attempts_by_paper(
    session: Session,
    *,
    paper_id: int,
) -> list[MasteryDrillAttempt]:
    drill = get_mastery_drill_session_by_paper(session, paper_id=paper_id)
    if drill is None or drill.id is None:
        return []
    return list_mastery_drill_attempts(session, drill_session_id=int(drill.id))


def get_mastery_drill_attempt_by_key(
    session: Session,
    *,
    drill_session_id: int,
    attempt_key: str,
) -> MasteryDrillAttempt | None:
    return session.exec(
        select(MasteryDrillAttempt).where(
            MasteryDrillAttempt.mastery_drill_session_id == drill_session_id,
            MasteryDrillAttempt.attempt_key == attempt_key,
        )
    ).first()


def get_active_mastery_drill_attempt_for_item(
    session: Session,
    *,
    item_id: int,
) -> MasteryDrillAttempt | None:
    return session.exec(
        select(MasteryDrillAttempt)
        .where(
            MasteryDrillAttempt.exam_paper_item_id == item_id,
            MasteryDrillAttempt.status == "grading",
        )
        .order_by(MasteryDrillAttempt.id.desc())
        .limit(1)
    ).first()


def _mastery_drill_item_is_passed(session: Session, *, item_id: int) -> bool:
    return session.exec(
        select(ExamPaperItem.id).where(
            ExamPaperItem.id == item_id,
            ExamPaperItem.is_correct.is_(True),
        )
    ).first() is not None


def claim_mastery_drill_attempt(
    session: Session,
    *,
    drill_session_id: int,
    item: ExamPaperItem,
    attempt_key: str,
    request_hash: str,
    answer: str,
    time_spent_seconds: int | None,
    hint_used: bool,
    confidence_self_report: int | None,
    claim_token: str,
    claimed_at: datetime,
    lease_expires_at: datetime,
) -> tuple[str, MasteryDrillAttempt]:
    """Claim one attempt before grading so retries cannot duplicate model calls."""

    item_id = int(item.id or 0)
    session.exec(
        sa.update(MasteryDrillAttempt)
        .where(
            MasteryDrillAttempt.exam_paper_item_id == item_id,
            MasteryDrillAttempt.status == "grading",
            MasteryDrillAttempt.lease_expires_at.is_not(None),
            MasteryDrillAttempt.lease_expires_at <= claimed_at,
        )
        .values(
            status="failed",
            claim_token="",
            lease_expires_at=None,
            error_code="attempt_grading_lease_expired",
            updated_at=claimed_at,
        )
        .execution_options(synchronize_session=False)
    )

    existing = get_mastery_drill_attempt_by_key(
        session,
        drill_session_id=drill_session_id,
        attempt_key=attempt_key,
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            return "conflict", existing
        if existing.status == "graded":
            session.commit()
            return "completed", existing
        if existing.status == "grading":
            session.commit()
            return "in_progress", existing
        if _mastery_drill_item_is_passed(session, item_id=item_id):
            session.commit()
            return "passed", existing
        result = session.exec(
            sa.update(MasteryDrillAttempt)
            .where(
                MasteryDrillAttempt.id == int(existing.id or 0),
                MasteryDrillAttempt.status == "failed",
            )
            .values(
                status="grading",
                claim_token=claim_token,
                lease_expires_at=lease_expires_at,
                error_code="",
                updated_at=claimed_at,
            )
            .execution_options(synchronize_session=False)
        )
        session.commit()
        session.expire_all()
        refreshed = session.get(MasteryDrillAttempt, int(existing.id or 0)) or existing
        return ("claimed" if int(result.rowcount or 0) == 1 else "in_progress"), refreshed

    active = get_active_mastery_drill_attempt_for_item(session, item_id=item_id)
    if active is not None:
        session.commit()
        return "in_progress", active
    if _mastery_drill_item_is_passed(session, item_id=item_id):
        session.commit()
        passed_attempt = session.exec(
            select(MasteryDrillAttempt)
            .where(
                MasteryDrillAttempt.exam_paper_item_id == item_id,
                MasteryDrillAttempt.status == "graded",
                MasteryDrillAttempt.is_correct.is_(True),
            )
            .order_by(MasteryDrillAttempt.answered_at.desc(), MasteryDrillAttempt.id.desc())
            .limit(1)
        ).first()
        if passed_attempt is not None:
            return "passed", passed_attempt

    attempt_no = int(
        session.exec(
            select(func.count())
            .select_from(MasteryDrillAttempt)
            .where(MasteryDrillAttempt.exam_paper_item_id == item_id)
        ).one()
    ) + 1
    attempt = MasteryDrillAttempt(
        mastery_drill_session_id=drill_session_id,
        exam_paper_item_id=item_id,
        question_template_id=int(item.question_template_id or 0),
        attempt_no=attempt_no,
        attempt_key=attempt_key,
        request_hash=request_hash,
        status="grading",
        answer_content=answer,
        time_spent_seconds=time_spent_seconds,
        hint_used=hint_used,
        confidence_self_report=confidence_self_report,
        claim_token=claim_token,
        lease_expires_at=lease_expires_at,
        created_at=claimed_at,
        updated_at=claimed_at,
    )
    try:
        with session.begin_nested():
            session.add(attempt)
            session.flush()
    except IntegrityError:
        session.expire_all()
        existing = get_mastery_drill_attempt_by_key(
            session,
            drill_session_id=drill_session_id,
            attempt_key=attempt_key,
        )
        if existing is None:
            existing = get_active_mastery_drill_attempt_for_item(session, item_id=item_id)
        if existing is None:
            raise
        session.commit()
        if existing.attempt_key == attempt_key and existing.request_hash != request_hash:
            return "conflict", existing
        return ("completed" if existing.status == "graded" else "in_progress"), existing
    session.commit()
    session.refresh(attempt)
    return "claimed", attempt


def finalize_mastery_drill_attempt(
    session: Session,
    *,
    attempt_id: int,
    claim_token: str,
    is_correct: bool,
    score_obtained: float,
    score_max: float,
    feedback_text: str,
    error_cause_label: str | None,
    grading_mode: str,
    answered_at: datetime,
) -> MasteryDrillAttempt | None:
    result = session.exec(
        sa.update(MasteryDrillAttempt)
        .where(
            MasteryDrillAttempt.id == attempt_id,
            MasteryDrillAttempt.status == "grading",
            MasteryDrillAttempt.claim_token == claim_token,
        )
        .values(
            status="graded",
            is_correct=is_correct,
            score_obtained=score_obtained,
            score_max=score_max,
            feedback_text=feedback_text,
            error_cause_label=error_cause_label,
            grading_mode=grading_mode,
            claim_token="",
            lease_expires_at=None,
            error_code="",
            answered_at=answered_at,
            updated_at=answered_at,
        )
        .execution_options(synchronize_session=False)
    )
    if int(result.rowcount or 0) != 1:
        session.rollback()
        return None

    attempt = session.get(MasteryDrillAttempt, attempt_id)
    if attempt is None:
        session.rollback()
        return None
    item = session.get(ExamPaperItem, int(attempt.exam_paper_item_id))
    drill = session.get(MasteryDrillSession, int(attempt.mastery_drill_session_id))
    if item is None or drill is None:
        session.rollback()
        return None

    item.answer_content = attempt.answer_content
    item.is_correct = is_correct
    item.score_obtained = score_obtained
    item.score_max = score_max
    item.feedback_text = feedback_text
    item.error_cause_label = error_cause_label
    item.time_spent_seconds = attempt.time_spent_seconds
    item.hint_used = attempt.hint_used
    item.confidence_self_report = attempt.confidence_self_report
    item.answered_at = answered_at
    item.graded_at = answered_at
    item.updated_at = answered_at
    session.add(item)
    session.exec(
        sa.update(MasteryDrillSession)
        .where(MasteryDrillSession.id == int(drill.id or 0))
        .values(
            total_attempts=MasteryDrillSession.total_attempts + 1,
            wrong_attempts=MasteryDrillSession.wrong_attempts + (0 if is_correct else 1),
            updated_at=answered_at,
        )
        .execution_options(synchronize_session=False)
    )
    session.exec(
        sa.update(ExamPaper)
        .where(ExamPaper.id == int(drill.exam_paper_id))
        .values(status="in_progress", updated_at=answered_at)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    session.expire_all()
    return session.get(MasteryDrillAttempt, attempt_id)


def renew_mastery_drill_attempt_lease(
    session: Session,
    *,
    attempt_id: int,
    claim_token: str,
    lease_expires_at: datetime,
) -> bool:
    result = session.exec(
        sa.update(MasteryDrillAttempt)
        .where(
            MasteryDrillAttempt.id == attempt_id,
            MasteryDrillAttempt.status == "grading",
            MasteryDrillAttempt.claim_token == claim_token,
        )
        .values(lease_expires_at=lease_expires_at, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def fail_mastery_drill_attempt(
    session: Session,
    *,
    attempt_id: int,
    claim_token: str,
    error_code: str,
) -> bool:
    now = utcnow()
    result = session.exec(
        sa.update(MasteryDrillAttempt)
        .where(
            MasteryDrillAttempt.id == attempt_id,
            MasteryDrillAttempt.status == "grading",
            MasteryDrillAttempt.claim_token == claim_token,
        )
        .values(
            status="failed",
            claim_token="",
            lease_expires_at=None,
            error_code=error_code[:80],
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def get_exam_paper_by_id(session: Session, paper_id: int) -> ExamPaper | None:
    return session.get(ExamPaper, paper_id)


def get_exam_profile_sync(session: Session, *, paper_id: int) -> ExamProfileSync | None:
    return session.exec(
        select(ExamProfileSync).where(ExamProfileSync.exam_paper_id == paper_id)
    ).first()


def ensure_exam_profile_sync(
    session: Session,
    *,
    paper: ExamPaper,
    status: str = "pending",
    trigger: str = "exam_graded",
    states_updated: int = 0,
    review_task_count: int = 0,
    next_attempt_at: datetime | None = None,
    auto_commit: bool = False,
) -> ExamProfileSync:
    paper_id = int(paper.id or 0)
    existing = get_exam_profile_sync(session, paper_id=paper_id)
    if existing is not None:
        return existing
    now = utcnow()
    task = ExamProfileSync(
        exam_paper_id=paper_id,
        course_id=paper.course_id,
        user_id=paper.user_id,
        status=status,
        trigger=trigger,
        states_updated=max(0, int(states_updated or 0)),
        review_task_count=max(0, int(review_task_count or 0)),
        next_attempt_at=(next_attempt_at or now) if status != "completed" else None,
        completed_at=now if status == "completed" else None,
        created_at=now,
        updated_at=now,
    )
    try:
        with session.begin_nested():
            session.add(task)
            session.flush()
    except IntegrityError:
        session.expire_all()
        existing = get_exam_profile_sync(session, paper_id=paper_id)
        if existing is None:
            raise
        return existing
    if auto_commit:
        session.commit()
        session.refresh(task)
    return task


def finalize_mastery_drill_session(
    session: Session,
    *,
    drill: MasteryDrillSession,
    paper: ExamPaper,
    completion_key: str,
    submission_hash: str,
    total_score: float,
    score_obtained: float,
    duration_seconds: int | None,
    completed_at: datetime,
) -> bool:
    """Atomically close the drill, grade its paper envelope, and enqueue Profile sync."""

    drill_result = session.exec(
        sa.update(MasteryDrillSession)
        .where(
            MasteryDrillSession.id == int(drill.id or 0),
            MasteryDrillSession.status == "active",
        )
        .values(
            status="completed",
            completion_key=completion_key,
            completed_at=completed_at,
            updated_at=completed_at,
        )
        .execution_options(synchronize_session=False)
    )
    paper_result = session.exec(
        sa.update(ExamPaper)
        .where(
            ExamPaper.id == int(paper.id or 0),
            ExamPaper.status.in_(("ready", "in_progress")),
        )
        .values(
            status="graded",
            submission_key=completion_key,
            submission_hash=submission_hash,
            submitted_at=completed_at,
            graded_at=completed_at,
            total_score=max(0.0, float(total_score)),
            score_obtained=max(0.0, float(score_obtained)),
            duration_seconds=duration_seconds,
            updated_at=completed_at,
        )
        .execution_options(synchronize_session=False)
    )
    if int(drill_result.rowcount or 0) != 1 or int(paper_result.rowcount or 0) != 1:
        session.rollback()
        return False

    ensure_exam_profile_sync(
        session,
        paper=paper,
        status="pending",
        trigger="mastery_drill_completed",
        next_attempt_at=completed_at,
        auto_commit=False,
    )
    session.commit()
    return True


def claim_exam_profile_sync(
    session: Session,
    *,
    paper_id: int,
    claim_token: str,
    claimed_at: datetime,
    lease_expires_at: datetime,
) -> bool:
    result = session.exec(
        sa.update(ExamProfileSync)
        .where(
            ExamProfileSync.exam_paper_id == paper_id,
            sa.or_(
                sa.and_(
                    ExamProfileSync.status.in_(("pending", "retry_wait")),
                    sa.or_(
                        ExamProfileSync.next_attempt_at.is_(None),
                        ExamProfileSync.next_attempt_at <= claimed_at,
                    ),
                ),
                sa.and_(
                    ExamProfileSync.status == "processing",
                    sa.or_(
                        ExamProfileSync.lease_expires_at.is_(None),
                        ExamProfileSync.lease_expires_at <= claimed_at,
                    ),
                ),
            ),
        )
        .values(
            status="processing",
            claim_token=claim_token,
            lease_expires_at=lease_expires_at,
            attempt_count=ExamProfileSync.attempt_count + 1,
            next_attempt_at=None,
            started_at=claimed_at,
            last_error_code="",
            updated_at=claimed_at,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def finalize_exam_profile_sync(
    session: Session,
    *,
    paper_id: int,
    claim_token: str,
    states_updated: int,
    review_task_count: int,
    completed_at: datetime,
) -> bool:
    result = session.exec(
        sa.update(ExamProfileSync)
        .where(
            ExamProfileSync.exam_paper_id == paper_id,
            ExamProfileSync.status == "processing",
            ExamProfileSync.claim_token == claim_token,
        )
        .values(
            status="completed",
            claim_token="",
            lease_expires_at=None,
            next_attempt_at=None,
            last_error_code="",
            states_updated=max(0, int(states_updated or 0)),
            review_task_count=max(0, int(review_task_count or 0)),
            completed_at=completed_at,
            updated_at=completed_at,
        )
        .execution_options(synchronize_session=False)
    )
    return int(result.rowcount or 0) == 1


def renew_exam_profile_sync_lease(
    session: Session,
    *,
    paper_id: int,
    claim_token: str,
    lease_expires_at: datetime,
) -> bool:
    result = session.exec(
        sa.update(ExamProfileSync)
        .where(
            ExamProfileSync.exam_paper_id == paper_id,
            ExamProfileSync.status == "processing",
            ExamProfileSync.claim_token == claim_token,
        )
        .values(lease_expires_at=lease_expires_at, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def release_exam_profile_sync(
    session: Session,
    *,
    paper_id: int,
    claim_token: str,
    status: str,
    next_attempt_at: datetime | None,
    error_code: str,
) -> bool:
    now = utcnow()
    result = session.exec(
        sa.update(ExamProfileSync)
        .where(
            ExamProfileSync.exam_paper_id == paper_id,
            ExamProfileSync.status == "processing",
            ExamProfileSync.claim_token == claim_token,
        )
        .values(
            status=status,
            claim_token="",
            lease_expires_at=None,
            next_attempt_at=next_attempt_at,
            last_error_code=error_code[:80],
            last_error_at=now,
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def request_exam_profile_sync_retry(
    session: Session,
    *,
    paper_id: int,
    requested_at: datetime,
) -> bool:
    result = session.exec(
        sa.update(ExamProfileSync)
        .where(
            ExamProfileSync.exam_paper_id == paper_id,
            ExamProfileSync.status.in_(("failed", "retry_wait")),
        )
        .values(
            status="pending",
            next_attempt_at=requested_at,
            claim_token="",
            lease_expires_at=None,
            manual_retry_count=ExamProfileSync.manual_retry_count + 1,
            last_error_code="",
            updated_at=requested_at,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def list_recoverable_exam_profile_syncs(
    session: Session,
    *,
    as_of: datetime,
    limit: int = 100,
) -> list[ExamProfileSync]:
    stmt = (
        select(ExamProfileSync)
        .where(
            sa.or_(
                sa.and_(
                    ExamProfileSync.status.in_(("pending", "retry_wait")),
                    sa.or_(
                        ExamProfileSync.next_attempt_at.is_(None),
                        ExamProfileSync.next_attempt_at <= as_of,
                    ),
                ),
                sa.and_(
                    ExamProfileSync.status == "processing",
                    sa.or_(
                        ExamProfileSync.lease_expires_at.is_(None),
                        ExamProfileSync.lease_expires_at <= as_of,
                    ),
                ),
            )
        )
        .order_by(ExamProfileSync.next_attempt_at.asc(), ExamProfileSync.id.asc())
        .limit(max(1, limit))
    )
    return list(session.exec(stmt).all())


def claim_exam_submission(
    session: Session,
    *,
    paper_id: int,
    submission_key: str,
    submission_hash: str,
    submitted_at: datetime,
) -> bool:
    """Atomically accept the first submission for a ready paper."""

    result = session.exec(
        sa.update(ExamPaper)
        .where(
            ExamPaper.id == paper_id,
            ExamPaper.status.in_(("ready", "in_progress")),
            ExamPaper.submission_hash == "",
        )
        .values(
            status="submitted",
            submission_key=submission_key,
            submission_hash=submission_hash,
            submitted_at=submitted_at,
            grading_last_error="",
            updated_at=submitted_at,
        )
    )
    return int(result.rowcount or 0) == 1


def claim_exam_grading(
    session: Session,
    *,
    paper_id: int,
    claim_token: str,
    claimed_at: datetime,
    lease_expires_at: datetime,
    max_attempts: int = 3,
) -> bool:
    """Claim one grading attempt, including takeover of an expired lease."""

    result = session.exec(
        sa.update(ExamPaper)
        .where(
            ExamPaper.id == paper_id,
            ExamPaper.grading_attempts < max(1, max_attempts),
            sa.or_(
                ExamPaper.status == "submitted",
                sa.and_(
                    ExamPaper.status == "grading",
                    sa.or_(
                        ExamPaper.grading_lease_expires_at.is_(None),
                        ExamPaper.grading_lease_expires_at <= claimed_at,
                    ),
                ),
            ),
        )
        .values(
            status="grading",
            grading_claim_token=claim_token,
            grading_lease_expires_at=lease_expires_at,
            grading_attempts=ExamPaper.grading_attempts + 1,
            grading_last_error="",
            updated_at=claimed_at,
        )
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def renew_exam_grading_lease(
    session: Session,
    *,
    paper_id: int,
    claim_token: str,
    lease_expires_at: datetime,
) -> bool:
    now = utcnow()
    result = session.exec(
        sa.update(ExamPaper)
        .where(
            ExamPaper.id == paper_id,
            ExamPaper.status == "grading",
            ExamPaper.grading_claim_token == claim_token,
        )
        .values(grading_lease_expires_at=lease_expires_at, updated_at=now)
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def release_exam_grading_claim(
    session: Session,
    *,
    paper_id: int,
    claim_token: str,
    error_message: str,
    terminal_when_exhausted: bool = True,
    max_attempts: int = 3,
) -> bool:
    """Release a failed claim, stopping automatic retries after the configured limit."""

    now = utcnow()
    result = session.exec(
        sa.update(ExamPaper)
        .where(
            ExamPaper.id == paper_id,
            ExamPaper.status == "grading",
            ExamPaper.grading_claim_token == claim_token,
        )
        .values(
            status=sa.case(
                (
                    sa.and_(
                        terminal_when_exhausted,
                        ExamPaper.grading_attempts >= max(1, max_attempts),
                    ),
                    "grading_failed",
                ),
                else_="submitted",
            ),
            grading_claim_token="",
            grading_lease_expires_at=None,
            grading_last_error=error_message[:4000],
            updated_at=now,
        )
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def fail_exhausted_exam_grading(
    session: Session,
    *,
    paper_id: int,
    as_of: datetime,
    max_attempts: int = 3,
    error_message: str = "grading_retry_exhausted",
) -> bool:
    """Close an exhausted submitted paper or expired grading lease."""

    result = session.exec(
        sa.update(ExamPaper)
        .where(
            ExamPaper.id == paper_id,
            ExamPaper.grading_attempts >= max(1, max_attempts),
            sa.or_(
                ExamPaper.status == "submitted",
                sa.and_(
                    ExamPaper.status == "grading",
                    sa.or_(
                        ExamPaper.grading_lease_expires_at.is_(None),
                        ExamPaper.grading_lease_expires_at <= as_of,
                    ),
                ),
            ),
        )
        .values(
            status="grading_failed",
            grading_claim_token="",
            grading_lease_expires_at=None,
            grading_last_error=sa.case(
                (ExamPaper.grading_last_error != "", ExamPaper.grading_last_error),
                else_=error_message[:4000],
            ),
            updated_at=as_of,
        )
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def restart_failed_exam_grading(
    session: Session,
    *,
    paper_id: int,
    submission_hash: str,
    restarted_at: datetime,
) -> bool:
    """Atomically begin a new bounded grading cycle for the saved submission."""

    result = session.exec(
        sa.update(ExamPaper)
        .where(
            ExamPaper.id == paper_id,
            ExamPaper.status == "grading_failed",
            ExamPaper.submission_hash == submission_hash,
        )
        .values(
            status="submitted",
            grading_claim_token="",
            grading_lease_expires_at=None,
            grading_attempts=0,
            grading_last_error="",
            updated_at=restarted_at,
        )
    )
    return int(result.rowcount or 0) == 1


def finalize_exam_grading_claim(
    session: Session,
    *,
    paper_id: int,
    claim_token: str,
    total_score: float,
    score_obtained: float,
    graded_at: datetime,
) -> bool:
    """Fence stale workers while moving the active grading claim to graded."""

    result = session.exec(
        sa.update(ExamPaper)
        .where(
            ExamPaper.id == paper_id,
            ExamPaper.status == "grading",
            ExamPaper.grading_claim_token == claim_token,
        )
        .values(
            status="graded",
            total_score=total_score,
            score_obtained=score_obtained,
            graded_at=graded_at,
            grading_claim_token="",
            grading_lease_expires_at=None,
            grading_last_error="",
            updated_at=graded_at,
        )
    )
    return int(result.rowcount or 0) == 1


def list_recoverable_exam_grading_papers(
    session: Session,
    *,
    as_of: datetime,
    limit: int = 100,
) -> list[ExamPaper]:
    stmt = (
        select(ExamPaper)
        .where(
            ExamPaper.visibility != "hidden",
            sa.or_(
                ExamPaper.status == "submitted",
                sa.and_(
                    ExamPaper.status == "grading",
                    sa.or_(
                        ExamPaper.grading_lease_expires_at.is_(None),
                        ExamPaper.grading_lease_expires_at <= as_of,
                    ),
                ),
            ),
        )
        .order_by(ExamPaper.submitted_at.asc(), ExamPaper.id.asc())
        .limit(max(1, limit))
    )
    return list(session.exec(stmt).all())


def list_items_by_paper(session: Session, paper_id: int) -> list[ExamPaperItem]:
    stmt = (
        select(ExamPaperItem)
        .where(ExamPaperItem.exam_paper_id == paper_id)
        .order_by(ExamPaperItem.item_order.asc())
    )
    return list(session.exec(stmt).all())


def list_items_by_papers(session: Session, paper_ids: list[int]) -> dict[int, list[ExamPaperItem]]:
    ids = sorted({int(item) for item in paper_ids if int(item or 0) > 0})
    if not ids:
        return {}

    rows = list(
        session.exec(
            select(ExamPaperItem)
            .where(ExamPaperItem.exam_paper_id.in_(ids))
            .order_by(ExamPaperItem.exam_paper_id.asc(), ExamPaperItem.item_order.asc())
        ).all()
    )
    grouped: dict[int, list[ExamPaperItem]] = {paper_id: [] for paper_id in ids}
    for item in rows:
        grouped.setdefault(int(item.exam_paper_id), []).append(item)
    return grouped


def list_exam_papers(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    limit: int,
    offset: int,
) -> tuple[list[ExamPaper], int]:
    user_visible_conditions = [
        ExamPaper.course_id == course_id,
        ExamPaper.user_id == user_id,
        ExamPaper.visibility != "hidden",
        sa.or_(
            ExamPaper.generation_origin != "prewarm",
            ExamPaper.claimed_at.is_not(None),
            ExamPaper.submitted_at.is_not(None),
            ExamPaper.graded_at.is_not(None),
        ),
        ExamPaper.exam_mode != "mastery_drill",
    ]
    total = session.exec(
        select(func.count())
        .select_from(ExamPaper)
        .where(*user_visible_conditions)
    ).one()
    rows = list(
        session.exec(
            select(ExamPaper)
            .where(*user_visible_conditions)
            .order_by(ExamPaper.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return rows, total


def list_stale_visible_generating_exam_papers(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    stale_before: datetime,
    limit: int = 20,
) -> list[ExamPaper]:
    rows = session.exec(
        select(ExamPaper)
        .where(
            ExamPaper.course_id == course_id,
            ExamPaper.user_id == user_id,
            ExamPaper.exam_mode != "mastery_drill",
            ExamPaper.visibility != "hidden",
            ExamPaper.status == "generating",
            ExamPaper.updated_at <= stale_before,
        )
        .order_by(ExamPaper.updated_at.asc(), ExamPaper.id.asc())
        .limit(max(1, limit))
    ).all()
    return list(rows)


def get_visible_active_exam_candidate(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    config_hash: str,
    question_count: int | None = None,
    stale_before: datetime | None = None,
) -> ExamPaper | None:
    now = utcnow()
    conditions = [
        ExamPaper.course_id == course_id,
        ExamPaper.user_id == user_id,
        ExamPaper.visibility != "hidden",
        ExamPaper.config_hash == config_hash,
        ExamPaper.status.in_(("ready", "generating")),
        sa.or_(ExamPaper.expires_at.is_(None), ExamPaper.expires_at > now),
    ]
    if question_count is not None:
        conditions.append(ExamPaper.total_items == int(question_count))
    if stale_before is not None:
        conditions.append(
            sa.or_(
                ExamPaper.status != "generating",
                ExamPaper.updated_at > stale_before,
            )
        )
    return session.exec(
        select(ExamPaper)
        .where(*conditions)
        .order_by(ExamPaper.status.desc(), ExamPaper.updated_at.desc(), ExamPaper.id.desc())
        .limit(1)
    ).first()


def claim_prepared_exam_paper(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    config_hash: str,
    question_count: int | None = None,
) -> ExamPaper | None:
    """Atomically-ish claim the oldest hidden active paper matching the config."""

    now = utcnow()
    conditions = [
        ExamPaper.course_id == course_id,
        ExamPaper.user_id == user_id,
        ExamPaper.visibility == "hidden",
        ExamPaper.status.in_(("ready", "generating")),
        ExamPaper.config_hash == config_hash,
        sa.or_(ExamPaper.expires_at.is_(None), ExamPaper.expires_at > now),
    ]
    if question_count is not None:
        conditions.append(ExamPaper.total_items == int(question_count))
    stmt = (
        select(ExamPaper)
        .where(*conditions)
        .order_by(ExamPaper.created_at.asc(), ExamPaper.id.asc())
        .limit(1)
    )
    paper = session.exec(stmt).first()
    if paper is None:
        return None
    paper.visibility = "visible"
    paper.generation_origin = "prewarm"
    paper.claimed_at = now
    paper.expires_at = None
    paper.updated_at = now
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def list_hidden_prepared_exam_candidates_by_shape(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    exam_mode: str,
    question_count: int,
    limit: int = 20,
) -> list[ExamPaper]:
    rows = session.exec(
        select(ExamPaper)
        .where(
            ExamPaper.course_id == course_id,
            ExamPaper.user_id == user_id,
            ExamPaper.visibility == "hidden",
            ExamPaper.generation_origin == "prewarm",
            ExamPaper.exam_mode == exam_mode,
            ExamPaper.total_items == int(question_count),
        )
        .order_by(ExamPaper.updated_at.desc(), ExamPaper.id.desc())
        .limit(max(1, limit))
    ).all()
    return list(rows)


def list_prewarm_exam_candidates_by_shape(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    exam_mode: str,
    question_count: int,
    limit: int = 20,
) -> list[ExamPaper]:
    rows = session.exec(
        select(ExamPaper)
        .where(
            ExamPaper.course_id == course_id,
            ExamPaper.user_id == user_id,
            ExamPaper.generation_origin == "prewarm",
            ExamPaper.exam_mode == exam_mode,
            ExamPaper.total_items == int(question_count),
        )
        .order_by(ExamPaper.updated_at.desc(), ExamPaper.id.desc())
        .limit(max(1, limit))
    ).all()
    return list(rows)


def claim_prepared_exam_paper_by_id(
    session: Session,
    *,
    paper_id: int,
) -> ExamPaper | None:
    now = utcnow()
    paper = session.get(ExamPaper, int(paper_id))
    if paper is None:
        return None
    if paper.visibility != "hidden" or paper.status not in {"ready", "generating"}:
        return None
    expires_at = ensure_utc_datetime(paper.expires_at)
    if expires_at is not None and expires_at <= now:
        return None

    paper.visibility = "visible"
    paper.generation_origin = "prewarm"
    paper.claimed_at = now
    paper.expires_at = None
    paper.updated_at = now
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def has_active_prepared_exam(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    config_hash: str,
    question_count: int | None = None,
) -> bool:
    now = utcnow()
    active_statuses = ("generating", "ready")
    conditions = [
        ExamPaper.course_id == course_id,
        ExamPaper.user_id == user_id,
        ExamPaper.config_hash == config_hash,
        ExamPaper.status.in_(active_statuses),
        sa.or_(ExamPaper.expires_at.is_(None), ExamPaper.expires_at > now),
    ]
    if question_count is not None:
        conditions.append(ExamPaper.total_items == int(question_count))
    existing = session.exec(
        select(ExamPaper.id)
        .where(*conditions)
        .limit(1)
    ).first()
    return existing is not None


def get_prepared_exam_candidate(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    config_hash: str,
    question_count: int | None = None,
) -> ExamPaper | None:
    now = utcnow()
    conditions = [
        ExamPaper.course_id == course_id,
        ExamPaper.user_id == user_id,
        ExamPaper.visibility == "hidden",
        ExamPaper.config_hash == config_hash,
    ]
    if question_count is not None:
        conditions.append(ExamPaper.total_items == int(question_count))
    candidates = list(
        session.exec(
            select(ExamPaper)
            .where(*conditions)
            .order_by(ExamPaper.updated_at.desc(), ExamPaper.id.desc())
            .limit(20)
        ).all()
    )
    if not candidates:
        return None

    def is_active(paper: ExamPaper) -> bool:
        expires_at = ensure_utc_datetime(paper.expires_at)
        return expires_at is None or expires_at > now

    for status in ("ready", "generating"):
        match = next((paper for paper in candidates if paper.status == status and is_active(paper)), None)
        if match is not None:
            return match

    failed = next((paper for paper in candidates if paper.status == "failed" and is_active(paper)), None)
    if failed is not None:
        return failed

    stale = next((paper for paper in candidates if not is_active(paper)), None)
    return stale or candidates[0]


def list_stale_hidden_exam_paper_ids(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    limit: int = 20,
) -> list[int]:
    now = utcnow()
    rows = session.exec(
        select(ExamPaper.id)
        .where(
            ExamPaper.course_id == course_id,
            ExamPaper.user_id == user_id,
            ExamPaper.visibility == "hidden",
            sa.or_(
                ExamPaper.status == "failed",
                sa.and_(ExamPaper.expires_at.is_not(None), ExamPaper.expires_at <= now),
            ),
        )
        .order_by(ExamPaper.updated_at.asc(), ExamPaper.id.asc())
        .limit(max(1, limit))
    ).all()
    return [int(item) for item in rows if item is not None]


def count_active_question_templates(
    session: Session,
    *,
    course_id: str,
    question_types: set[str] | None = None,
    difficulty: str | None = None,
) -> int:
    stmt = (
        select(func.count())
        .select_from(QuestionTemplate)
        .where(
            QuestionTemplate.course_id == course_id,
            QuestionTemplate.status == "active",
        )
    )
    if question_types:
        stmt = stmt.where(QuestionTemplate.question_type.in_(question_types))
    if difficulty:
        stmt = stmt.where(QuestionTemplate.difficulty == difficulty)
    return int(session.exec(stmt).one())


def list_active_question_templates(
    session: Session,
    *,
    course_id: str,
    unit_ids: set[int] | None = None,
    question_types: set[str] | None = None,
    difficulty: str | None = None,
) -> list[QuestionTemplate]:
    stmt = select(QuestionTemplate).where(
        QuestionTemplate.course_id == course_id,
        QuestionTemplate.status == "active",
    )
    if unit_ids:
        stmt = stmt.join(
            QuestionKnowledgeUnitLink,
            QuestionKnowledgeUnitLink.question_template_id == QuestionTemplate.id,
        ).where(QuestionKnowledgeUnitLink.knowledge_unit_id.in_(unit_ids)).distinct()
    if question_types:
        stmt = stmt.where(QuestionTemplate.question_type.in_(question_types))
    if difficulty:
        stmt = stmt.where(QuestionTemplate.difficulty == difficulty)
    return list(session.exec(stmt.order_by(QuestionTemplate.id)).all())


def list_exam_item_snapshots_by_user(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    limit: int | None = None,
) -> list[tuple[ExamPaperItem, datetime, int]]:
    stmt = (
        select(ExamPaperItem, ExamPaper.created_at, ExamPaper.id)
        .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
        .where(
            ExamPaper.course_id == course_id,
            ExamPaper.user_id == user_id,
            ExamPaper.exam_mode != "mastery_drill",
        )
        .order_by(ExamPaper.created_at.desc(), ExamPaper.id.desc(), ExamPaperItem.item_order.asc())
    )
    if limit is not None and limit > 0:
        stmt = stmt.limit(limit)
    rows = list(session.exec(stmt).all())
    normalized: list[tuple[ExamPaperItem, datetime, int]] = []
    for row in rows:
        item, asked_at, exam_paper_id = row
        normalized.append((item, asked_at, int(exam_paper_id)))
    return normalized


def delete_exam_paper_cascade(session: Session, *, paper_id: int) -> bool:
    paper = session.get(ExamPaper, paper_id)
    if paper is None:
        return False

    item_ids = [
        item_id
        for item_id in session.exec(select(ExamPaperItem.id).where(ExamPaperItem.exam_paper_id == paper_id)).all()
        if item_id is not None
    ]

    session.exec(
        sa.update(UserKnowledgeState)
        .where(UserKnowledgeState.source_exam_paper_id == paper_id)
        .values(source_exam_paper_id=None)
    )
    # Keep the completed one-time marker even when the generated paper is
    # deleted. Otherwise deleting history could accidentally re-enable the
    # automatic initial exam.
    session.exec(
        sa.update(CourseInitialExamJob)
        .where(CourseInitialExamJob.exam_paper_id == paper_id)
        .values(exam_paper_id=None, updated_at=utcnow())
    )

    if item_ids:
        session.exec(
            sa.delete(MasteryDrillAttempt).where(
                MasteryDrillAttempt.exam_paper_item_id.in_(item_ids)
            )
        )
        session.exec(
            sa.delete(QuestionKnowledgeUnitLink).where(
                QuestionKnowledgeUnitLink.exam_paper_item_id.in_(item_ids)
            )
        )

    session.exec(sa.delete(ExamPaperItem).where(ExamPaperItem.exam_paper_id == paper_id))
    session.exec(sa.delete(MasteryDrillSession).where(MasteryDrillSession.exam_paper_id == paper_id))
    session.exec(sa.delete(ExamProfileSync).where(ExamProfileSync.exam_paper_id == paper_id))

    session.delete(paper)
    session.commit()
    return True


def get_study_guide_cache(session: Session, *, exam_paper_id: int) -> ExamStudyGuideCache | None:
    return session.exec(
        select(ExamStudyGuideCache).where(ExamStudyGuideCache.exam_paper_id == exam_paper_id)
    ).first()


def claim_study_guide_generation(
    session: Session,
    *,
    exam_paper_id: int,
    course_id: str,
    user_id: str,
    expected_cache: ExamStudyGuideCache | None,
    generation_json: str,
) -> bool:
    """Atomically claim one study-guide generation from an observed cache snapshot."""

    now = utcnow()
    if expected_cache is None:
        try:
            session.add(
                ExamStudyGuideCache(
                    exam_paper_id=exam_paper_id,
                    course_id=course_id,
                    user_id=user_id,
                    status="generating",
                    guide_json=generation_json,
                    error_message="",
                    generated_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.commit()
            return True
        except IntegrityError:
            # Another request inserted the unique paper cache first.
            session.rollback()
            return False

    result = session.exec(
        sa.update(ExamStudyGuideCache)
        .where(
            ExamStudyGuideCache.exam_paper_id == exam_paper_id,
            ExamStudyGuideCache.status == expected_cache.status,
            ExamStudyGuideCache.guide_json == expected_cache.guide_json,
        )
        .values(
            course_id=course_id,
            user_id=user_id,
            status="generating",
            guide_json=generation_json,
            error_message="",
            generated_at=None,
            updated_at=now,
        )
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def update_owned_study_guide_cache(
    session: Session,
    *,
    exam_paper_id: int,
    generation_token: str,
    status: str,
    guide_json: str,
    error_message: str = "",
    generated_at: datetime | None = None,
) -> bool:
    """Fence stale workers by updating only the cache owned by their token."""

    normalized_token = str(generation_token or "").strip()
    if not normalized_token:
        return False
    now = utcnow()
    result = session.exec(
        sa.update(ExamStudyGuideCache)
        .where(
            ExamStudyGuideCache.exam_paper_id == exam_paper_id,
            ExamStudyGuideCache.status == "generating",
            ExamStudyGuideCache.guide_json.like(f'%"generation_token":"{normalized_token}"%'),
        )
        .values(
            status=status,
            guide_json=guide_json,
            error_message=error_message,
            generated_at=generated_at,
            updated_at=now,
        )
    )
    session.commit()
    return int(result.rowcount or 0) == 1


def upsert_study_guide_cache(
    session: Session,
    *,
    exam_paper_id: int,
    course_id: str,
    user_id: str,
    status: str,
    guide_json: str,
    error_message: str = "",
    generated_at: datetime | None = None,
) -> ExamStudyGuideCache:
    now = utcnow()
    cache = get_study_guide_cache(session, exam_paper_id=exam_paper_id)
    if cache is None:
        cache = ExamStudyGuideCache(
            exam_paper_id=exam_paper_id,
            course_id=course_id,
            user_id=user_id,
            created_at=now,
        )
    cache.status = status
    cache.guide_json = guide_json
    cache.error_message = error_message
    cache.generated_at = generated_at
    cache.updated_at = now
    session.add(cache)
    session.commit()
    session.refresh(cache)
    return cache


def list_recent_exam_template_ids_for_user(
    session: Session,
    user_id: str,
    course_id: str,
    *,
    limit: int = 3,
) -> list[int]:
    if limit <= 0:
        return []

    recent_exam_ids_subquery = (
        select(ExamPaper.id)
        .where(ExamPaper.user_id == user_id, ExamPaper.course_id == course_id)
        .order_by(ExamPaper.created_at.desc())
        .limit(limit)
        .subquery()
    )

    stmt = (
        select(ExamPaperItem.question_template_id)
        .where(ExamPaperItem.exam_paper_id.in_(select(recent_exam_ids_subquery.c.id)))
        .distinct()
    )
    return [int(item) for item in session.exec(stmt).all()]
