"""Knowledge-graph debug cleanup commands."""

from __future__ import annotations

import sqlalchemy as sa
from sqlmodel import Session, func, select

from app.models import KnowledgeEdge, KnowledgeUnit
from app.shared.infra.exceptions import SubjectBuildLockConflictError
from app.utils.docgen_store import is_knowledge_build_locked


def clear_subject_graph_entities(session: Session, *, subject: str) -> dict[str, int]:
    if is_knowledge_build_locked(subject):
        raise SubjectBuildLockConflictError(subject)

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

    session.exec(sa.delete(KnowledgeEdge).where(KnowledgeEdge.subject == subject))
    session.exec(sa.delete(KnowledgeUnit).where(KnowledgeUnit.subject == subject))
    session.commit()

    return {
        "knowledge_edge": edge_count,
        "knowledge_unit": node_count,
    }


__all__ = ["clear_subject_graph_entities"]
