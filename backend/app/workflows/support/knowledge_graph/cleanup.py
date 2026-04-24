"""Knowledge-graph debug cleanup commands."""

from __future__ import annotations

import sqlalchemy as sa
from sqlmodel import Session, func, select

from app.models import ExamPaperItem, KnowledgeEdge, KnowledgeUnit, QuestionTemplate, UserKnowledgeState
from app.shared.infra.exceptions import SubjectBuildLockConflictError
from app.shared.infra.knowledge.build_store import is_knowledge_build_locked


def clear_subject_graph_entities(session: Session, *, subject: str) -> dict[str, int]:
    if is_knowledge_build_locked(subject):
        raise SubjectBuildLockConflictError(subject)

    unit_ids = list(
        session.exec(
            select(KnowledgeUnit.id).where(KnowledgeUnit.subject == subject)
        ).all()
    )
    edge_count = int(
        session.exec(
            select(func.count()).select_from(KnowledgeEdge).where(KnowledgeEdge.subject == subject)
        ).one()
    )
    node_count = int(
        session.exec(
            select(func.count()).select_from(KnowledgeUnit).where(KnowledgeUnit.subject == subject)
        ).one()
    )

    detached_template_count = 0
    detached_exam_item_count = 0
    detached_state_count = 0
    detached_merge_ref_count = 0

    if unit_ids:
        detached_template_count = int(
            session.exec(
                sa.update(QuestionTemplate)
                .where(
                    QuestionTemplate.subject == subject,
                    QuestionTemplate.knowledge_unit_id.in_(unit_ids),
                )
                .values(knowledge_unit_id=None, knowledge_unit_refs_json="[]")
            ).rowcount
            or 0
        )
        detached_exam_item_count = int(
            session.exec(
                sa.update(ExamPaperItem)
                .where(ExamPaperItem.knowledge_unit_id.in_(unit_ids))
                .values(knowledge_unit_id=None, knowledge_unit_refs_json="[]")
            ).rowcount
            or 0
        )
        detached_state_count = int(
            session.exec(
                sa.update(UserKnowledgeState)
                .where(
                    UserKnowledgeState.subject == subject,
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

    session.exec(sa.delete(KnowledgeEdge).where(KnowledgeEdge.subject == subject))
    session.exec(sa.delete(KnowledgeUnit).where(KnowledgeUnit.subject == subject))
    session.commit()

    return {
        "knowledge_edge": edge_count,
        "knowledge_unit": node_count,
        "detached_question_template": detached_template_count,
        "detached_exam_paper_item": detached_exam_item_count,
        "detached_user_knowledge_state": detached_state_count,
        "detached_unit_merge_ref": detached_merge_ref_count,
    }


__all__ = ["clear_subject_graph_entities"]
