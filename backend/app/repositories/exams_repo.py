"""Exam data access layer."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Session, func, select

from app.models import (
    ExamPaper,
    ExamPaperItem,
    ExamStudyGuideCache,
    QuestionKnowledgeUnitLink,
    QuestionTemplate,
    UserKnowledgeState,
)
from app.utils.time import ensure_utc_datetime, utcnow


def create_question_template(session: Session, template: QuestionTemplate) -> QuestionTemplate:
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

    rows = session.exec(
        select(ExamPaperItem.question_template_id)
        .join(ExamPaper, ExamPaper.id == ExamPaperItem.exam_paper_id)
        .where(
            ExamPaperItem.question_template_id.in_(ids),
            ExamPaperItem.is_correct.is_(False),
            ExamPaper.course_id == course_id,
            ExamPaper.user_id == user_id,
            ExamPaper.visibility != "hidden",
        )
        .distinct()
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
        session.add(item)
    if auto_commit:
        session.commit()
        for item in items:
            session.refresh(item)
    else:
        session.flush()
    return items


def get_exam_paper_by_id(session: Session, paper_id: int) -> ExamPaper | None:
    return session.get(ExamPaper, paper_id)


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
    total = session.exec(
        select(func.count())
        .select_from(ExamPaper)
        .where(
            ExamPaper.course_id == course_id,
            ExamPaper.user_id == user_id,
            ExamPaper.visibility != "hidden",
        )
    ).one()
    rows = list(
        session.exec(
            select(ExamPaper)
            .where(
                ExamPaper.course_id == course_id,
                ExamPaper.user_id == user_id,
                ExamPaper.visibility != "hidden",
            )
            .order_by(ExamPaper.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return rows, total


def claim_prepared_exam_paper(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    config_hash: str,
) -> ExamPaper | None:
    """Atomically-ish claim the oldest hidden active paper matching the config."""

    now = utcnow()
    stmt = (
        select(ExamPaper)
        .where(
            ExamPaper.course_id == course_id,
            ExamPaper.user_id == user_id,
            ExamPaper.visibility == "hidden",
            ExamPaper.status.in_(("ready", "generating")),
            ExamPaper.config_hash == config_hash,
            sa.or_(ExamPaper.expires_at.is_(None), ExamPaper.expires_at > now),
        )
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


def has_active_prepared_exam(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    config_hash: str,
) -> bool:
    now = utcnow()
    active_statuses = ("generating", "ready")
    existing = session.exec(
        select(ExamPaper.id)
        .where(
            ExamPaper.course_id == course_id,
            ExamPaper.user_id == user_id,
            ExamPaper.visibility == "hidden",
            ExamPaper.config_hash == config_hash,
            ExamPaper.status.in_(active_statuses),
            sa.or_(ExamPaper.expires_at.is_(None), ExamPaper.expires_at > now),
        )
        .limit(1)
    ).first()
    return existing is not None


def get_prepared_exam_candidate(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    config_hash: str,
) -> ExamPaper | None:
    now = utcnow()
    candidates = list(
        session.exec(
            select(ExamPaper)
            .where(
                ExamPaper.course_id == course_id,
                ExamPaper.user_id == user_id,
                ExamPaper.visibility == "hidden",
                ExamPaper.config_hash == config_hash,
            )
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

    if item_ids:
        session.exec(
            sa.delete(QuestionKnowledgeUnitLink).where(
                QuestionKnowledgeUnitLink.exam_paper_item_id.in_(item_ids)
            )
        )

    session.exec(sa.delete(ExamPaperItem).where(ExamPaperItem.exam_paper_id == paper_id))

    session.delete(paper)
    session.commit()
    return True


def get_study_guide_cache(session: Session, *, exam_paper_id: int) -> ExamStudyGuideCache | None:
    return session.exec(
        select(ExamStudyGuideCache).where(ExamStudyGuideCache.exam_paper_id == exam_paper_id)
    ).first()


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
