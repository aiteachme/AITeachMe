"""Knowledge-graph debug cleanup commands."""

from __future__ import annotations

import sqlalchemy as sa
from sqlmodel import Session, func, select

from app.models import ExamPaper, ExamPaperItem, KnowledgeEdge, KnowledgeUnit, QuestionKnowledgeUnitLink, QuestionTemplate, UserKnowledgeState
from app.shared.infra.exceptions import CourseBuildLockConflictError
from app.shared.infra.knowledge.build_store import is_knowledge_build_locked


def clear_course_graph_entities(session: Session, *, course_id: str) -> dict[str, int]:
    if is_knowledge_build_locked(course_id):
        raise CourseBuildLockConflictError(course_id)

    unit_ids = list(
        session.exec(
            select(KnowledgeUnit.id).where(KnowledgeUnit.course_id == course_id)
        ).all()
    )
    edge_count = int(
        session.exec(
        select(func.count()).select_from(KnowledgeEdge).where(KnowledgeEdge.course_id == course_id)
        ).one()
    )
    node_count = int(
        session.exec(
        select(func.count()).select_from(KnowledgeUnit).where(KnowledgeUnit.course_id == course_id)
        ).one()
    )

    detached_template_count = 0
    detached_exam_item_count = 0
    detached_state_count = 0
    detached_merge_ref_count = 0

    if unit_ids:
        detached_template_count = int(
            session.exec(
                select(func.count(func.distinct(QuestionKnowledgeUnitLink.question_template_id)))
                .select_from(QuestionKnowledgeUnitLink)
                .join(QuestionTemplate, QuestionKnowledgeUnitLink.question_template_id == QuestionTemplate.id)
                .where(
                    QuestionTemplate.course_id == course_id,
                    QuestionKnowledgeUnitLink.knowledge_unit_id.in_(unit_ids),
                )
            ).one()
        )
        detached_exam_item_count = int(
            session.exec(
                select(func.count(func.distinct(QuestionKnowledgeUnitLink.exam_paper_item_id)))
                .select_from(QuestionKnowledgeUnitLink)
                .join(ExamPaperItem, QuestionKnowledgeUnitLink.exam_paper_item_id == ExamPaperItem.id)
                .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
                .where(
                    ExamPaper.course_id == course_id,
                    QuestionKnowledgeUnitLink.knowledge_unit_id.in_(unit_ids),
                )
            ).one()
        )
        session.exec(
            sa.delete(QuestionKnowledgeUnitLink).where(
                QuestionKnowledgeUnitLink.knowledge_unit_id.in_(unit_ids)
            )
        )
        detached_state_count = int(
            session.exec(
                sa.update(UserKnowledgeState)
                .where(
                    UserKnowledgeState.course_id == course_id,
                    UserKnowledgeState.knowledge_unit_id.in_(unit_ids),
                )
                .values(knowledge_unit_id=None)
            ).rowcount
            or 0
        )
        detached_merge_ref_count = int(
            session.exec(
                sa.update(KnowledgeUnit)
                .where(KnowledgeUnit.merged_into_knowledge_unit_id.in_(unit_ids))
                .values(merged_into_knowledge_unit_id=None)
            ).rowcount
            or 0
        )

    session.exec(sa.delete(KnowledgeEdge).where(KnowledgeEdge.course_id == course_id))
    session.exec(sa.delete(KnowledgeUnit).where(KnowledgeUnit.course_id == course_id))
    session.commit()

    return {
        "knowledge_edge": edge_count,
        "knowledge_unit": node_count,
        "detached_question_template": detached_template_count,
        "detached_exam_paper_item": detached_exam_item_count,
        "detached_user_knowledge_state": detached_state_count,
        "detached_unit_merge_ref": detached_merge_ref_count,
    }


__all__ = ["clear_course_graph_entities"]
