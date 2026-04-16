"""Exam data access layer."""

from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import Session, func, select

from app.models import (
    Curriculum,
    ExamPaper,
    ExamPaperItem,
    QuestionTemplate,
    TeachingUnit,
    ThemeTreeNode,
    UnitDependency,
)
from app.repositories.knowledge import curriculum_repo


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
    stmt = select(QuestionTemplate).where(QuestionTemplate.teaching_unit_id == unit_id)
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
        QuestionTemplate.teaching_unit_id == unit_id,
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


def list_teaching_unit_ids_by_subject(
    session: Session,
    *,
    subject: str,
    status: str | None = "active",
) -> list[int]:
    stmt = select(TeachingUnit.id).where(TeachingUnit.subject == subject)
    if status is not None:
        stmt = stmt.where(TeachingUnit.status == status)
    stmt = stmt.order_by(TeachingUnit.id)
    return [int(item) for item in session.exec(stmt).all() if item is not None]


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
    curriculum_version_id: int | None = None,
    unit_ids: set[int] | None = None,
    question_types: set[str] | None = None,
    difficulty: str | None = None,
) -> list[QuestionTemplate]:
    stmt = select(QuestionTemplate).where(
        QuestionTemplate.subject == subject,
        QuestionTemplate.status == "active",
    )
    if curriculum_version_id is not None:
        stmt = stmt.where(QuestionTemplate.curriculum_version_id == curriculum_version_id)
    if unit_ids:
        stmt = stmt.where(QuestionTemplate.teaching_unit_id.in_(unit_ids))
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

    paper_items = list_items_by_paper(session, paper_id)
    for item in paper_items:
        session.delete(item)

    session.delete(paper)
    session.commit()
    return True


def get_published_curriculum_version(
    session: Session,
    subject: str,
) -> Curriculum | None:
    return curriculum_repo.get_current_curriculum_snapshot(session, subject)


def resolve_teaching_units_from_theme_tree_node(
    session: Session,
    theme_tree_node_id: int,
) -> list[int]:
    node = session.get(ThemeTreeNode, theme_tree_node_id)
    if node is None:
        return []

    teaching_unit_ids: list[int] = []
    for item in _load_json_list(node.unit_refs_json):
        raw_unit_id = item.get("teaching_unit_id")
        if isinstance(raw_unit_id, int):
            teaching_unit_ids.append(raw_unit_id)
    return sorted(set(teaching_unit_ids))


def list_prereq_units(session: Session, unit_id: int) -> list[int]:
    unit = session.get(TeachingUnit, unit_id)
    if unit is None:
        return []

    curriculum = get_published_curriculum_version(session, unit.subject)
    if curriculum is None or curriculum.id is None:
        return []

    stmt = (
        select(UnitDependency.source_unit_id)
        .where(
            UnitDependency.dag_version_id == curriculum.id,
            UnitDependency.target_unit_id == unit_id,
            UnitDependency.dependency_type == "prerequisite",
        )
        .distinct()
        .order_by(UnitDependency.source_unit_id)
    )
    return [int(item) for item in session.exec(stmt).all()]


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
