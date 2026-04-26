"""Exam data access layer."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Session, func, select

from app.models import (
    ExamPaper,
    ExamPaperItem,
    QuestionKnowledgeUnitLink,
    QuestionTemplate,
    UserKnowledgeState,
)


def create_question_template(session: Session, template: QuestionTemplate) -> QuestionTemplate:
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


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
                "role": str(ref.get("role", "primary" if not normalized else "secondary") or "secondary"),
            }
        )
    return normalized


def _link_payload(link: QuestionKnowledgeUnitLink) -> dict[str, object]:
    return {
        "knowledge_unit_id": int(link.knowledge_unit_id),
        "coverage_weight": float(link.coverage_weight),
        "role": str(link.role or "secondary"),
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
            role=str(ref["role"]),
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
            role=str(ref["role"]),
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
    subject: str,
    unit_id: int,
    stem_hash: str,
) -> QuestionTemplate | None:
    stmt = select(QuestionTemplate).where(
        QuestionTemplate.subject == subject,
        QuestionTemplate.stem_hash == stem_hash,
    )
    rows = list(session.exec(stmt).all())
    if not rows:
        return None
    template_ids = [int(item.id or 0) for item in rows]
    linked_ids = {
        int(item)
        for item in session.exec(
            select(QuestionKnowledgeUnitLink.question_template_id)
            .where(
                QuestionKnowledgeUnitLink.question_template_id.in_(template_ids),
                QuestionKnowledgeUnitLink.knowledge_unit_id == unit_id,
            )
        ).all()
        if item is not None
    }
    return next((item for item in rows if int(item.id or 0) in linked_ids), None)


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


def list_exam_papers(
    session: Session,
    *,
    subject: str,
    user_id: str,
    limit: int,
    offset: int,
) -> tuple[list[ExamPaper], int]:
    total = session.exec(
        select(func.count())
        .select_from(ExamPaper)
        .where(ExamPaper.subject == subject, ExamPaper.user_id == user_id)
    ).one()
    rows = list(
        session.exec(
            select(ExamPaper)
            .where(ExamPaper.subject == subject, ExamPaper.user_id == user_id)
            .order_by(ExamPaper.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    return rows, total


def count_active_question_templates(
    session: Session,
    *,
    subject: str,
    question_types: set[str] | None = None,
    difficulty: str | None = None,
) -> int:
    stmt = (
        select(func.count())
        .select_from(QuestionTemplate)
        .where(
            QuestionTemplate.subject == subject,
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
    subject: str,
    unit_ids: set[int] | None = None,
    question_types: set[str] | None = None,
    difficulty: str | None = None,
) -> list[QuestionTemplate]:
    stmt = select(QuestionTemplate).where(
        QuestionTemplate.subject == subject,
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
    subject: str,
    user_id: str,
    limit: int | None = None,
) -> list[tuple[ExamPaperItem, datetime, int]]:
    stmt = (
        select(ExamPaperItem, ExamPaper.created_at, ExamPaper.id)
        .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
        .where(
            ExamPaper.subject == subject,
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


def list_recent_exam_template_ids_for_user(
    session: Session,
    user_id: str,
    subject: str,
    *,
    limit: int = 3,
) -> list[int]:
    if limit <= 0:
        return []

    recent_exam_ids_subquery = (
        select(ExamPaper.id)
        .where(ExamPaper.user_id == user_id, ExamPaper.subject == subject)
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
