"""Exam data access layer."""

from __future__ import annotations

import json
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Session, func, select

from app.models import (
    ExamPaper,
    ExamPaperItem,
    QuestionTemplate,
    UserKnowledgeState,
)


def _load_json_list(payload: str) -> list[dict[str, object]]:
    try:
        decoded = json.loads(payload or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, dict)]


def _dump_json_list(payload: list[dict[str, object]]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def create_question_template(session: Session, template: QuestionTemplate) -> QuestionTemplate:
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


def create_template_knowledge_unit_links(session: Session, links: list) -> list:
    grouped: dict[int, list[dict[str, object]]] = {}
    for item in links:
        template_id = getattr(item, "question_template_id", None)
        node_id = getattr(item, "knowledge_unit_id", None)
        if template_id is None or node_id is None:
            continue
        grouped.setdefault(int(template_id), []).append(
            {
                "knowledge_unit_id": int(node_id),
                "coverage_weight": float(getattr(item, "coverage_weight", 1.0)),
                "role": str(getattr(item, "role", "primary")),
            }
        )

    for template_id, node_refs in grouped.items():
        template = session.get(QuestionTemplate, template_id)
        if template is None:
            continue
        template.knowledge_unit_refs_json = _dump_json_list(node_refs)
        session.add(template)

    session.commit()
    return links


def find_templates_by_unit(
    session: Session,
    unit_id: int,
    *,
    status: str = "active",
) -> list[QuestionTemplate]:
    stmt = select(QuestionTemplate).where(QuestionTemplate.knowledge_unit_id == unit_id)
    if status:
        stmt = stmt.where(QuestionTemplate.status == status)
    return list(session.exec(stmt.order_by(QuestionTemplate.id)).all())


def find_templates_by_node(
    session: Session,
    node_id: int,
    *,
    status: str = "active",
) -> list[QuestionTemplate]:
    stmt = select(QuestionTemplate)
    if status:
        stmt = stmt.where(QuestionTemplate.status == status)

    rows = list(session.exec(stmt.order_by(QuestionTemplate.id)).all())
    matched: list[QuestionTemplate] = []
    for item in rows:
        if any(ref.get("knowledge_unit_id") == node_id for ref in _load_json_list(item.knowledge_unit_refs_json)):
            matched.append(item)
    return matched


def find_template_by_stem_hash(
    session: Session,
    subject: str,
    unit_id: int,
    stem_hash: str,
) -> QuestionTemplate | None:
    stmt = select(QuestionTemplate).where(
        QuestionTemplate.subject == subject,
        QuestionTemplate.knowledge_unit_id == unit_id,
        QuestionTemplate.stem_hash == stem_hash,
    )
    return session.exec(stmt).first()


def find_knowledge_unit_links_by_template(session: Session, template_id: int) -> list[dict[str, object]]:
    template = session.get(QuestionTemplate, template_id)
    if template is None:
        return []
    return _load_json_list(template.knowledge_unit_refs_json)


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
        stmt = stmt.where(QuestionTemplate.knowledge_unit_id.in_(unit_ids))
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

    session.exec(
        sa.update(UserKnowledgeState)
        .where(UserKnowledgeState.source_exam_paper_id == paper_id)
        .values(source_exam_paper_id=None)
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
