from __future__ import annotations

import asyncio
import re
import shutil
from typing import Any

import sqlalchemy as sa
import structlog
from sqlmodel import Session, func, select

from app.shared.infra.storage import (
    build_subject_storage_scope,
    get_content_store,
    resolve_subject_storage_scope,
    run_store_sync,
)
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
    QuestionKnowledgeUnitLink,
    QuestionTemplate,
    QuestionTypeRegistry,
    RawFile,
    RetrievalChunk,
    Subject,
    SubjectFileLink,
    UserKnowledgeState,
)
from app.schemas.subject import SubjectDeleteImpactItem, SubjectDeletePreviewData
from app.utils.path_helpers import build_subject_dir, get_data_dir

logger = structlog.get_logger()
_POSTGRES_IDENTIFIER_RE = re.compile(r"[a-z_][a-z0-9_]*")

_EXAM_KEYS = [
    "question_template",
    "question_type_registry",
    "exam_paper",
    "exam_paper_item",
]
_PROFILE_KEYS = ["user_knowledge_state"]
_KNOWLEDGE_KEYS = [
    "knowledge_graph_source_ref",
    "knowledge_graph_sync_run",
    "knowledge_document",
    "knowledge_edge",
    "knowledge_unit",
]


def _count_query(session: Session, statement) -> int:
    return int(session.exec(statement).one())


def _count_rows(session: Session, model: type, *conditions: object) -> int:
    return _count_query(session, select(func.count()).select_from(model).where(*conditions))


def _sum_counts(counts: dict[str, int], keys: list[str]) -> int:
    return sum(counts.get(key, 0) for key in keys)


def _bulk_delete_by_subject(session: Session, model: type, *, subject_id: str) -> None:
    session.exec(
        sa.delete(model)
        .where(model.subject_id == subject_id)
        .execution_options(synchronize_session=False)
    )


def _raw_file_subject_membership_condition(subject_id: str):
    linked_file_ids = select(SubjectFileLink.file_id).where(SubjectFileLink.subject_id == subject_id)
    return RawFile.id.in_(linked_file_ids)


def _count_raw_files_by_subject(session: Session, *, subject_id: str) -> int:
    return _count_rows(session, RawFile, _raw_file_subject_membership_condition(subject_id))


def collect_subject_delete_counts(session: Session, *, subject_id: str) -> dict[str, int]:
    return {
        "raw_file": _count_raw_files_by_subject(session, subject_id=subject_id),
        "retrieval_chunk": _count_rows(session, RetrievalChunk, RetrievalChunk.subject_id == subject_id),
        "knowledge_document": _count_rows(
            session,
            KnowledgeDocument,
            KnowledgeDocument.subject_id == subject_id,
        ),
        "chat_message": _count_rows(session, ChatMessage, ChatMessage.subject_id == subject_id),
        "chat_session": _count_rows(session, ChatSession, ChatSession.subject_id == subject_id),
        "question_template": _count_rows(session, QuestionTemplate, QuestionTemplate.subject_id == subject_id),
        "question_type_registry": _count_rows(session, QuestionTypeRegistry, QuestionTypeRegistry.subject_id == subject_id),
        "exam_paper": _count_rows(session, ExamPaper, ExamPaper.subject_id == subject_id),
        "exam_paper_item": _count_query(
            session,
            select(func.count())
            .select_from(ExamPaperItem)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(ExamPaper.subject_id == subject_id),
        ),
        "user_knowledge_state": _count_rows(session, UserKnowledgeState, UserKnowledgeState.subject_id == subject_id),
        "knowledge_edge": _count_rows(session, KnowledgeEdge, KnowledgeEdge.subject_id == subject_id),
        "knowledge_unit": _count_rows(session, KnowledgeUnit, KnowledgeUnit.subject_id == subject_id),
        "knowledge_graph_sync_run": _count_rows(session, KnowledgeGraphSyncRun, KnowledgeGraphSyncRun.subject_id == subject_id),
        "knowledge_graph_source_ref": _count_rows(
            session,
            KnowledgeGraphSourceRef,
            KnowledgeGraphSourceRef.subject_id == subject_id,
        ),
    }


def build_subject_delete_preview(session: Session, *, subject: Subject) -> SubjectDeletePreviewData:
    detail_counts = collect_subject_delete_counts(session, subject_id=subject.id)
    total_related_records = sum(detail_counts.values())
    impact_items = [
        SubjectDeleteImpactItem(
            key="files",
            label="上传文件与切块",
            count=detail_counts["raw_file"] + detail_counts["retrieval_chunk"],
            description="会移除文件与该学科的关联，并删除该学科下的切块与向量索引。",
        ),
        SubjectDeleteImpactItem(
            key="knowledge",
            label="知识结构与讲义",
            count=_sum_counts(detail_counts, _KNOWLEDGE_KEYS),
            description="会删除知识文档、图谱、课程树与依赖结构。",
        ),
        SubjectDeleteImpactItem(
            key="exam",
            label="考试记录",
            count=_sum_counts(detail_counts, _EXAM_KEYS),
            description="会删除题模板、试卷与试卷题目快照。",
        ),
        SubjectDeleteImpactItem(
            key="chat",
            label="对话记录",
            count=detail_counts["chat_message"] + detail_counts["chat_session"],
            description="会删除该学科下的会话与聊天消息。",
        ),
        SubjectDeleteImpactItem(
            key="profile",
            label="学习画像",
            count=_sum_counts(detail_counts, _PROFILE_KEYS),
            description="会删除 mastery 与复习状态。",
        ),
    ]
    return SubjectDeletePreviewData(
        subject_id=subject.id,
        subject_name=subject.name,
        has_content=total_related_records > 0,
        total_related_records=total_related_records,
        impact_items=[item for item in impact_items if item.count > 0],
        detail_counts=detail_counts,
    )


def delete_subject_with_all_content(
    session: Session,
    *,
    subject: Subject,
    background_task_registry: Any | None = None,
    counts: dict[str, int] | None = None,
) -> dict[str, int]:
    subject_id = subject.id
    owner_user_id = subject.user_id
    counts = dict(counts) if counts is not None else collect_subject_delete_counts(session, subject_id=subject_id)
    try:
        _delete_profiles(session, subject_id=subject_id)
        _delete_exam_records(session, subject_id=subject_id)
        _delete_chat_messages(session, subject_id=subject_id)
        _delete_knowledge_and_curriculum(session, subject_id=subject_id)
        _delete_documents_and_chunks(session, subject_id=subject_id)
        _delete_planner_records(session, subject_id=subject_id)
        _delete_raw_files_and_artifacts(session, subject_id=subject_id, owner_user_id=owner_user_id)
        session.delete(subject)
        session.commit()
    except Exception:
        session.rollback()
        raise

    _schedule_subject_external_cleanup(
        subject_id,
        owner_user_id=owner_user_id,
        background_task_registry=background_task_registry,
    )
    deleted_counts = {"subject": 1, **counts}
    logger.info("subject_deleted_with_all_content", subject_id=subject_id, subject_name=subject.name, deleted_counts=deleted_counts)
    return deleted_counts


async def delete_subject_artifacts_async(subject_id: str, *, user_id: str | None = None) -> None:
    """Delete all stored files for one subject through ContentStore."""

    cs = get_content_store()
    scope = (
        build_subject_storage_scope(user_id=user_id, subject_id=subject_id)
        if user_id
        else resolve_subject_storage_scope(subject_id)
    )
    await cs.delete_prefix(scope.subject_prefix())
    # Also clean local runtime directories when present.
    _delete_subject_directory(subject_id, user_id=user_id)


def _delete_subject_artifacts_best_effort(subject_id: str, *, user_id: str | None) -> None:
    cs = get_content_store()
    try:
        scope = build_subject_storage_scope(user_id=user_id or "local", subject_id=subject_id)
        run_store_sync(cs.delete_prefix, scope.subject_prefix(), default=0)
    except Exception as exc:  # pragma: no cover - best-effort cleanup
        logger.warning("subject_artifact_prefix_cleanup_failed", subject_id=subject_id, error=str(exc))
    _delete_subject_directory(subject_id, user_id=user_id)


def _schedule_subject_external_cleanup(
    subject_id: str,
    *,
    owner_user_id: str | None,
    background_task_registry: Any | None,
) -> None:
    if background_task_registry is None:
        _delete_subject_external_artifacts_best_effort(subject_id, user_id=owner_user_id)
        return

    background_task_registry.spawn(
        _delete_subject_external_artifacts_async(subject_id, user_id=owner_user_id),
        kind="subjects.delete.cleanup",
        subject_id=subject_id,
        name=f"subjects.delete.cleanup:{subject_id}",
    )


async def _delete_subject_external_artifacts_async(subject_id: str, *, user_id: str | None) -> None:
    await asyncio.to_thread(
        _delete_subject_external_artifacts_best_effort,
        subject_id,
        user_id=user_id,
    )


def _delete_subject_external_artifacts_best_effort(subject_id: str, *, user_id: str | None) -> None:
    _clear_subject_vector_index_best_effort(subject_id, user_id=user_id)
    _delete_subject_artifacts_best_effort(subject_id, user_id=user_id)
    logger.info("subject_external_artifacts_cleanup_finished", subject_id=subject_id, user_id=user_id)


def _delete_exam_records(session: Session, *, subject_id: str) -> None:
    paper_ids = select(ExamPaper.id).where(ExamPaper.subject_id == subject_id)
    template_ids = select(QuestionTemplate.id).where(QuestionTemplate.subject_id == subject_id)
    paper_item_ids = select(ExamPaperItem.id).where(ExamPaperItem.exam_paper_id.in_(paper_ids))
    template_item_ids = select(ExamPaperItem.id).where(ExamPaperItem.question_template_id.in_(template_ids))

    session.exec(
        sa.delete(QuestionKnowledgeUnitLink)
        .where(
            sa.or_(
                QuestionKnowledgeUnitLink.exam_paper_item_id.in_(paper_item_ids),
                QuestionKnowledgeUnitLink.exam_paper_item_id.in_(template_item_ids),
                QuestionKnowledgeUnitLink.question_template_id.in_(template_ids),
            )
        )
        .execution_options(synchronize_session=False)
    )
    session.exec(
        sa.delete(ExamPaperItem)
        .where(
            sa.or_(
                ExamPaperItem.exam_paper_id.in_(paper_ids),
                ExamPaperItem.question_template_id.in_(template_ids),
            )
        )
        .execution_options(synchronize_session=False)
    )

    _bulk_delete_by_subject(session, ExamPaper, subject_id=subject_id)
    _bulk_delete_by_subject(session, QuestionTemplate, subject_id=subject_id)
    _bulk_delete_by_subject(session, QuestionTypeRegistry, subject_id=subject_id)


def _delete_chat_messages(session: Session, *, subject_id: str) -> None:
    _bulk_delete_by_subject(session, ChatMessage, subject_id=subject_id)
    _bulk_delete_by_subject(session, ChatSession, subject_id=subject_id)


def _delete_profiles(session: Session, *, subject_id: str) -> None:
    _bulk_delete_by_subject(session, UserKnowledgeState, subject_id=subject_id)


def _delete_knowledge_and_curriculum(session: Session, *, subject_id: str) -> None:
    session.exec(
        sa.update(KnowledgeDocument)
        .where(KnowledgeDocument.subject_id == subject_id)
        .values(root_document_id=None, parent_document_id=None)
    )
    session.exec(
        sa.update(KnowledgeUnit)
        .where(KnowledgeUnit.subject_id == subject_id)
        .values(merged_into_knowledge_unit_id=None)
    )
    _bulk_delete_by_subject(session, KnowledgeGraphSourceRef, subject_id=subject_id)
    _bulk_delete_by_subject(session, KnowledgeGraphSyncRun, subject_id=subject_id)
    _bulk_delete_by_subject(session, KnowledgeEdge, subject_id=subject_id)
    _bulk_delete_by_subject(session, KnowledgeDocument, subject_id=subject_id)
    _bulk_delete_by_subject(session, KnowledgeUnit, subject_id=subject_id)


def _delete_documents_and_chunks(session: Session, *, subject_id: str) -> None:
    _bulk_delete_by_subject(session, RetrievalChunk, subject_id=subject_id)


def _clear_subject_vector_index_best_effort(subject_id: str, *, user_id: str | None) -> None:
    try:
        from app.shared.infra.runtime import is_cloud_mode

        if is_cloud_mode():
            from app.shared.infra.database import get_engine
            from app.shared.infra.subject import (
                build_subject_index_ref,
                extract_postgres_subject_index_data_table_name,
            )

            vector_ref = build_subject_index_ref(subject_id, owner_user_id=user_id or "local")
            data_table = extract_postgres_subject_index_data_table_name(vector_ref)
            if not data_table or not _POSTGRES_IDENTIFIER_RE.fullmatch(data_table):
                return
            with get_engine().begin() as connection:
                connection.execute(sa.text(f"DROP TABLE IF EXISTS public.{data_table}"))
        else:
            from app.shared.infra.search.llamaindex_index import clear_subject_index

            clear_subject_index(subject_id)
    except Exception as exc:  # pragma: no cover - best-effort index cleanup
        logger.warning("subject_vector_index_cleanup_failed", subject_id=subject_id, error=str(exc))


def _delete_planner_records(session: Session, *, subject_id: str) -> None:
    del session, subject_id


def _delete_raw_files_and_artifacts(session: Session, *, subject_id: str, owner_user_id: str) -> None:
    session.exec(
        sa.delete(SubjectFileLink)
        .where(
            SubjectFileLink.user_id == owner_user_id,
            SubjectFileLink.subject_id == subject_id,
        )
        .execution_options(synchronize_session=False)
    )


def _delete_subject_directory(subject_id: str, *, user_id: str | None = None) -> None:
    subject_dirs = {
        build_subject_dir(subject_id, user_id=user_id),
        get_data_dir() / subject_id,  # Best-effort cleanup for legacy top-level folders.
    }
    for subject_dir in subject_dirs:
        if subject_dir.exists():
            shutil.rmtree(subject_dir, ignore_errors=True)
