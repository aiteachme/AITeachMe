"""Exam read queries: history, question bank, detail, delete."""

from __future__ import annotations

import structlog
from sqlmodel import Session, select

from app.models import ExamPaperItem, KnowledgeUnit, QuestionTemplate
from app.repositories import exams_repo
from app.schemas.common import PaginatedData, build_paginated_data

from ._helpers import (
    ExamPaperDetail,
    QuestionBankItem,
    _parse_json_list,
    _raise_not_found,
    _resolve_template_knowledge_points,
    _summarize_style_hint,
)

logger = structlog.get_logger()


async def get_exam_history(
    session: Session,
    *,
    subject: str,
    user_id: str,
    page: int,
    size: int,
):
    rows, total = exams_repo.list_exam_papers(
        session,
        subject=subject,
        user_id=user_id,
        limit=size,
        offset=(page - 1) * size,
    )
    return build_paginated_data(items=rows, page=page, size=size, total=total)


async def get_question_bank(
    session: Session,
    *,
    subject: str,
    user_id: str,
) -> list[QuestionBankItem]:
    rows = exams_repo.list_exam_item_snapshots_by_user(
        session,
        subject=subject,
        user_id=user_id,
    )
    agg: dict[int, QuestionBankItem] = {}
    style_summary_by_template: dict[int, str | None] = {}
    knowledge_points_by_template: dict[int, list[str]] = {}

    template_ids = list({int(item.question_template_id) for item, _, _ in rows if item.question_template_id is not None})
    if template_ids:
        templates = list(session.exec(select(QuestionTemplate).where(QuestionTemplate.id.in_(template_ids))).all())
        style_summary_by_template = {
            int(template.id): _summarize_style_hint(template.selection_hints_json)
            for template in templates
            if template.id is not None
        }
        knowledge_points_by_template = _resolve_template_knowledge_points(session, template_ids=template_ids)

    for item, asked_at, exam_paper_id in rows:
        template_id = int(item.question_template_id)
        existing = agg.get(template_id)
        if existing is None:
            agg[template_id] = QuestionBankItem(
                question_template_id=template_id,
                stem=item.stem_snapshot,
                question_type=item.question_type,
                difficulty=item.difficulty,
                teaching_unit_id=item.teaching_unit_id,
                times_asked=1,
                last_asked_at=asked_at,
                last_exam_paper_id=exam_paper_id,
                knowledge_points=knowledge_points_by_template.get(template_id, []),
                style_summary=style_summary_by_template.get(template_id),
            )
            continue

        latest_time = existing.last_asked_at
        latest_paper_id = existing.last_exam_paper_id
        if asked_at > existing.last_asked_at:
            latest_time = asked_at
            latest_paper_id = exam_paper_id
        agg[template_id] = QuestionBankItem(
            question_template_id=existing.question_template_id,
            stem=existing.stem,
            question_type=existing.question_type,
            difficulty=existing.difficulty,
            teaching_unit_id=existing.teaching_unit_id,
            times_asked=existing.times_asked + 1,
            last_asked_at=latest_time,
            last_exam_paper_id=latest_paper_id,
            knowledge_points=existing.knowledge_points,
            style_summary=existing.style_summary,
        )
    return sorted(agg.values(), key=lambda item: item.last_asked_at, reverse=True)


async def delete_exam_paper(
    session: Session,
    *,
    subject: str,
    user_id: str,
    exam_paper_id: int,
) -> None:
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != subject or paper.user_id != user_id:
        _raise_not_found(f"试卷 `{exam_paper_id}` 不存在。", error_code="EXAM_PAPER_NOT_FOUND")

    deleted = exams_repo.delete_exam_paper_cascade(session, paper_id=exam_paper_id)
    if not deleted:
        _raise_not_found(f"试卷 `{exam_paper_id}` 不存在。", error_code="EXAM_PAPER_NOT_FOUND")


async def get_exam_paper_detail(
    session: Session,
    *,
    subject: str,
    user_id: str,
    exam_paper_id: int,
) -> ExamPaperDetail:
    paper = exams_repo.get_exam_paper_by_id(session, exam_paper_id)
    if paper is None or paper.subject != subject or paper.user_id != user_id:
        _raise_not_found(f"试卷 `{exam_paper_id}` 不存在。", error_code="EXAM_PAPER_NOT_FOUND")

    items = list(
        session.exec(
            select(ExamPaperItem)
            .where(ExamPaperItem.exam_paper_id == exam_paper_id)
            .order_by(ExamPaperItem.item_order)
        ).all()
    )
    attempts_by_item_id: dict[int, ExamPaperItem] = {}
    for item in items:
        if item.id is None:
            continue
        if not (item.answer_content or item.is_correct is not None):
            continue
        attempts_by_item_id[item.id] = item

    return ExamPaperDetail(paper=paper, items=items, attempts_by_item_id=attempts_by_item_id)
