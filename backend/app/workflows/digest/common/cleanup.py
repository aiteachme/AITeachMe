"""Digest-wide knowledge cleanup commands."""

from __future__ import annotations

import sqlalchemy as sa
import structlog
from sqlmodel import Session, func, select

from app.models import (
    ChatMessage,
    ChatSession,
    ExamPaper,
    ExamPaperItem,
    KnowledgeDocument,
    KnowledgeEdge,
    KnowledgeGraphSourceRef,
    KnowledgeGraphSyncRun,
    KnowledgeUnit,
    QuestionTemplate,
    RetrievalChunk,
    UserKnowledgeState,
)
import app.repositories.knowledge.knowledge_repo as knowledge_repo
from app.shared.infra.exceptions import KnowledgeClearConflictError, CourseBuildLockConflictError
from app.shared.infra.knowledge.build_store import clear_knowledge_runtime_artifacts, is_knowledge_build_locked
from app.workflows.support.courses.learning_context import clear_course_learning_context

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


def _bulk_delete_by_course(session: Session, model: type, *, course_id: str) -> None:
    session.exec(sa.delete(model).where(model.course_id == course_id))


def _collect_blocking_counts(session: Session, *, course_id: str) -> dict[str, int]:
    return {
        "chat_message": _count_rows(session, ChatMessage, ChatMessage.course_id == course_id),
        "chat_session": _count_rows(session, ChatSession, ChatSession.course_id == course_id),
        "question_template": _count_rows(session, QuestionTemplate, QuestionTemplate.course_id == course_id),
        "exam_paper": _count_rows(session, ExamPaper, ExamPaper.course_id == course_id),
        "exam_paper_item": _count_query(
            session,
            select(func.count())
            .select_from(ExamPaperItem)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(ExamPaper.course_id == course_id),
        ),
        "user_knowledge_state": _count_rows(
            session,
            UserKnowledgeState,
            UserKnowledgeState.course_id == course_id,
        ),
    }


def _format_blocking_details(blocking_counts: dict[str, int]) -> str:
    details: list[str] = []
    for key, count in blocking_counts.items():
        if count <= 0:
            continue
        details.append(f"{_BLOCKING_LABELS[key]} {count} 条")
    return "，".join(details)


def _ensure_knowledge_can_be_cleared(session: Session, *, course_id: str) -> None:
    if is_knowledge_build_locked(course_id):
        raise CourseBuildLockConflictError(course_id)

    blocking_counts = _collect_blocking_counts(session, course_id=course_id)
    if any(count > 0 for count in blocking_counts.values()):
        raise KnowledgeClearConflictError(course_id, _format_blocking_details(blocking_counts))


def clear_course_knowledge(session: Session, *, course_id: str) -> dict[str, int]:
    """Clear all digest knowledge artifacts for one course."""

    _ensure_knowledge_can_be_cleared(session, course_id=course_id)

    counts: dict[str, int] = {}

    chunks = list(session.exec(select(RetrievalChunk).where(RetrievalChunk.course_id == course_id)).all())
    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    if chunk_ids:
        knowledge_repo.delete_embeddings_by_chunk_ids(session, course_id=course_id, chunk_ids=chunk_ids)
    for chunk in chunks:
        session.delete(chunk)
    counts["retrieval_chunk"] = len(chunks)
    session.commit()

    knowledge_documents = list(
        session.exec(select(KnowledgeDocument).where(KnowledgeDocument.course_id == course_id)).all()
    )
    counts["knowledge_document"] = len(knowledge_documents)

    edges = list(session.exec(select(KnowledgeEdge).where(KnowledgeEdge.course_id == course_id)).all())
    counts["knowledge_edge"] = len(edges)

    nodes = list(session.exec(select(KnowledgeUnit).where(KnowledgeUnit.course_id == course_id)).all())
    counts["knowledge_unit"] = len(nodes)

    source_refs = list(
        session.exec(select(KnowledgeGraphSourceRef).where(KnowledgeGraphSourceRef.course_id == course_id)).all()
    )
    counts["knowledge_graph_source_ref"] = len(source_refs)

    sync_runs = list(
        session.exec(select(KnowledgeGraphSyncRun).where(KnowledgeGraphSyncRun.course_id == course_id)).all()
    )
    counts["knowledge_graph_sync_run"] = len(sync_runs)

    for model in (
        KnowledgeGraphSourceRef,
        KnowledgeGraphSyncRun,
        KnowledgeDocument,
        KnowledgeEdge,
        KnowledgeUnit,
    ):
        _bulk_delete_by_course(session, model, course_id=course_id)
    clear_course_learning_context(session, course_id=course_id)
    session.commit()

    clear_knowledge_runtime_artifacts(course_id)
    logger.info("course_knowledge_cleared", course_id=course_id, counts=counts)
    return counts


__all__ = ["clear_course_knowledge"]
