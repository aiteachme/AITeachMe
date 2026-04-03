"""Knowledge cleanup commands."""

from __future__ import annotations

import sqlalchemy as sa
import structlog
from sqlmodel import Session, func, select

from app.shared.infra.exceptions import KnowledgeClearConflictError, SubjectBuildLockConflictError
from app.models import (
    ChatMessage,
    ChatSession,
    Curriculum,
    ExamPaper,
    ExamPaperItem,
    KnowledgeDocument,
    KnowledgeEdge,
    KnowledgeNode,
    QuestionTemplate,
    RetrievalChunk,
    TaxonomyAnchor,
    TeachingUnit,
    ThemeTreeNode,
    UnitDependency,
    UserKnowledgeState,
)
from app.repositories.knowledge import knowledge_repo
from app.utils.docgen_store import clear_knowledge_runtime_artifacts, is_knowledge_build_locked

logger = structlog.get_logger()

_BLOCKING_LABELS = {
    "chat_message": "聊天消息",
    "chat_session": "聊天会话",
    "question_template": "题模板",
    "exam_paper": "试卷",
    "exam_paper_item": "试卷题目快照",
    "user_knowledge_state": "学习画像",
}


def _count_query(session: Session, statement) -> int:
    return int(session.exec(statement).one())


def _count_rows(session: Session, model: type, *conditions: object) -> int:
    return _count_query(session, select(func.count()).select_from(model).where(*conditions))


def _bulk_delete_by_subject(session: Session, model: type, *, subject: str) -> None:
    session.exec(sa.delete(model).where(model.subject == subject))


def _collect_blocking_counts(session: Session, *, subject: str) -> dict[str, int]:
    return {
        "chat_message": _count_rows(session, ChatMessage, ChatMessage.subject == subject),
        "chat_session": _count_rows(session, ChatSession, ChatSession.subject == subject),
        "question_template": _count_rows(session, QuestionTemplate, QuestionTemplate.subject == subject),
        "exam_paper": _count_rows(session, ExamPaper, ExamPaper.subject == subject),
        "exam_paper_item": _count_query(
            session,
            select(func.count())
            .select_from(ExamPaperItem)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(ExamPaper.subject == subject),
        ),
        "user_knowledge_state": _count_rows(
            session,
            UserKnowledgeState,
            UserKnowledgeState.subject == subject,
        ),
    }


def _format_blocking_details(blocking_counts: dict[str, int]) -> str:
    details: list[str] = []
    for key, count in blocking_counts.items():
        if count <= 0:
            continue
        details.append(f"{_BLOCKING_LABELS[key]} {count} 条")
    return "，".join(details)


def _ensure_knowledge_can_be_cleared(session: Session, *, subject: str) -> None:
    if is_knowledge_build_locked(subject):
        raise SubjectBuildLockConflictError(subject)

    blocking_counts = _collect_blocking_counts(session, subject=subject)
    if any(count > 0 for count in blocking_counts.values()):
        raise KnowledgeClearConflictError(subject, _format_blocking_details(blocking_counts))


def clear_subject_knowledge(session: Session, *, subject: str) -> dict[str, int]:
    _ensure_knowledge_can_be_cleared(session, subject=subject)

    counts: dict[str, int] = {}

    chunks = list(session.exec(select(RetrievalChunk).where(RetrievalChunk.subject == subject)).all())
    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    if chunk_ids:
        knowledge_repo.delete_embeddings_by_chunk_ids(session, subject=subject, chunk_ids=chunk_ids)
    for chunk in chunks:
        session.delete(chunk)
    counts["retrieval_chunk"] = len(chunks)
    session.commit()

    knowledge_documents = list(
        session.exec(select(KnowledgeDocument).where(KnowledgeDocument.subject == subject)).all()
    )
    counts["knowledge_document"] = len(knowledge_documents)

    tree_nodes = list(session.exec(select(ThemeTreeNode).where(ThemeTreeNode.subject == subject)).all())
    counts["theme_tree_node"] = len(tree_nodes)

    dependencies = list(session.exec(select(UnitDependency).where(UnitDependency.subject == subject)).all())
    counts["unit_dependency"] = len(dependencies)

    curricula = list(session.exec(select(Curriculum).where(Curriculum.subject == subject)).all())
    counts["curriculum"] = len(curricula)
    counts["curriculum_version"] = 0
    counts["theme_tree_version"] = 0
    counts["prereq_dag_version"] = 0

    anchors = list(session.exec(select(TaxonomyAnchor).where(TaxonomyAnchor.subject == subject)).all())
    counts["taxonomy_anchor"] = len(anchors)

    units = list(session.exec(select(TeachingUnit).where(TeachingUnit.subject == subject)).all())
    counts["teaching_unit"] = len(units)

    edges = list(session.exec(select(KnowledgeEdge).where(KnowledgeEdge.subject == subject)).all())
    counts["knowledge_edge"] = len(edges)

    nodes = list(session.exec(select(KnowledgeNode).where(KnowledgeNode.subject == subject)).all())
    counts["knowledge_node"] = len(nodes)

    for model in (
        KnowledgeDocument,
        ThemeTreeNode,
        UnitDependency,
        TaxonomyAnchor,
        KnowledgeEdge,
        KnowledgeNode,
        TeachingUnit,
        Curriculum,
    ):
        _bulk_delete_by_subject(session, model, subject=subject)
    session.commit()

    clear_knowledge_runtime_artifacts(subject)
    logger.info("subject_knowledge_cleared", subject=subject, counts=counts)
    return counts


__all__ = ["clear_subject_knowledge"]
