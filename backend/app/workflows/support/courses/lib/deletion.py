"""Course cascade deletion helpers and preview counters."""

from __future__ import annotations

import asyncio
import re
import shutil
from typing import Any

import sqlalchemy as sa
import structlog
from sqlmodel import Session, func, select

from app.shared.infra.storage import (
    build_course_storage_scope,
    get_content_store,
    resolve_course_storage_scope,
    run_store_sync,
)
from app.models import (
    ChatMessage,
    ChatSession,
    ExamPaper,
    ExamPaperItem,
    ExamStudyGuideCache,
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
    Course,
    CourseFileLink,
    CourseShare,
    UserKnowledgeState,
)
from app.schemas.course import CourseDeletePreviewData
from app.utils.path_helpers import build_course_dir
from app.utils.time import utcnow

logger = structlog.get_logger()
_POSTGRES_IDENTIFIER_RE = re.compile(r"[a-z_][a-z0-9_]*")



def _count_query(session: Session, statement) -> int:
    return int(session.exec(statement).one())


def _count_rows(session: Session, model: type, *conditions: object) -> int:
    return _count_query(session, select(func.count()).select_from(model).where(*conditions))


def _bulk_delete_by_course(session: Session, model: type, *, course_id: str) -> None:
    session.exec(
        sa.delete(model)
        .where(model.course_id == course_id)
        .execution_options(synchronize_session=False)
    )


def _raw_file_course_membership_condition(course_id: str):
    linked_file_ids = select(CourseFileLink.file_id).where(CourseFileLink.course_id == course_id)
    return RawFile.id.in_(linked_file_ids)


def _count_raw_files_by_course(session: Session, *, course_id: str) -> int:
    return _count_rows(session, RawFile, _raw_file_course_membership_condition(course_id))


def collect_course_delete_counts(session: Session, *, course_id: str) -> dict[str, int]:
    return {
        "raw_file": _count_raw_files_by_course(session, course_id=course_id),
        "retrieval_chunk": _count_rows(session, RetrievalChunk, RetrievalChunk.course_id == course_id),
        "knowledge_document": _count_rows(
            session,
            KnowledgeDocument,
            KnowledgeDocument.course_id == course_id,
        ),
        "chat_message": _count_rows(session, ChatMessage, ChatMessage.course_id == course_id),
        "chat_session": _count_rows(session, ChatSession, ChatSession.course_id == course_id),
        "question_template": _count_rows(session, QuestionTemplate, QuestionTemplate.course_id == course_id),
        "question_type_registry": _count_rows(session, QuestionTypeRegistry, QuestionTypeRegistry.course_id == course_id),
        "exam_paper": _count_rows(session, ExamPaper, ExamPaper.course_id == course_id),
        "exam_study_guide_cache": _count_rows(
            session,
            ExamStudyGuideCache,
            ExamStudyGuideCache.course_id == course_id,
        ),
        "exam_paper_item": _count_query(
            session,
            select(func.count())
            .select_from(ExamPaperItem)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(ExamPaper.course_id == course_id),
        ),
        "user_knowledge_state": _count_rows(session, UserKnowledgeState, UserKnowledgeState.course_id == course_id),
        "knowledge_edge": _count_rows(session, KnowledgeEdge, KnowledgeEdge.course_id == course_id),
        "knowledge_unit": _count_rows(session, KnowledgeUnit, KnowledgeUnit.course_id == course_id),
        "knowledge_graph_sync_run": _count_rows(session, KnowledgeGraphSyncRun, KnowledgeGraphSyncRun.course_id == course_id),
        "knowledge_graph_source_ref": _count_rows(
            session,
            KnowledgeGraphSourceRef,
            KnowledgeGraphSourceRef.course_id == course_id,
        ),
        "course_share": _count_rows(session, CourseShare, CourseShare.source_course_id == course_id),
    }


def build_course_delete_preview(session: Session, *, course: Course) -> CourseDeletePreviewData:
    detail_counts = collect_course_delete_counts(session, course_id=course.id)
    total_related_records = sum(detail_counts.values())
    return CourseDeletePreviewData(
        course_id=course.id,
        course_name=course.name,
        has_content=total_related_records > 0,
        total_related_records=total_related_records,
        impact_items=[],
        detail_counts=detail_counts,
    )


def delete_course_with_all_content(
    session: Session,
    *,
    course: Course,
    background_task_registry: Any | None = None,
    counts: dict[str, int] | None = None,
) -> dict[str, int]:
    course_id = course.id
    owner_user_id = course.user_id
    counts = dict(counts) if counts is not None else collect_course_delete_counts(session, course_id=course_id)
    try:
        _revoke_course_shares(session, course_id=course_id)
        _delete_profiles(session, course_id=course_id)
        _delete_exam_records(session, course_id=course_id)
        _delete_chat_messages(session, course_id=course_id)
        _delete_knowledge_and_curriculum(session, course_id=course_id)
        _delete_documents_and_chunks(session, course_id=course_id)
        _delete_planner_records(session, course_id=course_id)
        _delete_raw_files_and_artifacts(session, course_id=course_id, owner_user_id=owner_user_id)
        session.delete(course)
        session.commit()
    except Exception:
        session.rollback()
        raise

    _schedule_course_external_cleanup(
        course_id,
        owner_user_id=owner_user_id,
        background_task_registry=background_task_registry,
    )
    deleted_counts = {"course": 1, **counts}
    logger.info("course_deleted_with_all_content", course_id=course_id, course_name=course.name, deleted_counts=deleted_counts)
    return deleted_counts


async def delete_course_artifacts_async(course_id: str, *, user_id: str | None = None) -> None:
    """Delete all stored files for one course through ContentStore."""

    cs = get_content_store()
    scope = (
        build_course_storage_scope(user_id=user_id, course_id=course_id)
        if user_id
        else resolve_course_storage_scope(course_id)
    )
    await cs.delete_prefix(scope.course_prefix())
    # Also clean local runtime directories when present.
    _delete_course_directory(course_id, user_id=user_id)


def _delete_course_artifacts_best_effort(course_id: str, *, user_id: str | None) -> None:
    cs = get_content_store()
    try:
        scope = build_course_storage_scope(user_id=user_id or "local", course_id=course_id)
        run_store_sync(cs.delete_prefix, scope.course_prefix(), default=0)
    except Exception as exc:  # pragma: no cover - best-effort cleanup
        logger.warning("course_artifact_prefix_cleanup_failed", course_id=course_id, error=str(exc))
    _delete_course_directory(course_id, user_id=user_id)


def _schedule_course_external_cleanup(
    course_id: str,
    *,
    owner_user_id: str | None,
    background_task_registry: Any | None,
) -> None:
    if background_task_registry is None:
        _delete_course_external_artifacts_best_effort(course_id, user_id=owner_user_id)
        return

    background_task_registry.spawn(
        _delete_course_external_artifacts_async(course_id, user_id=owner_user_id),
        kind="courses.delete.cleanup",
        course_id=course_id,
        name=f"courses.delete.cleanup:{course_id}",
        dedupe_key=f"courses.delete.cleanup:{course_id}",
    )


async def _delete_course_external_artifacts_async(course_id: str, *, user_id: str | None) -> None:
    await asyncio.to_thread(
        _delete_course_external_artifacts_best_effort,
        course_id,
        user_id=user_id,
    )


def _delete_course_external_artifacts_best_effort(course_id: str, *, user_id: str | None) -> None:
    _clear_course_vector_index_best_effort(course_id, user_id=user_id)
    _delete_course_artifacts_best_effort(course_id, user_id=user_id)
    logger.info("course_external_artifacts_cleanup_finished", course_id=course_id, user_id=user_id)


def _delete_exam_records(session: Session, *, course_id: str) -> None:
    paper_ids = select(ExamPaper.id).where(ExamPaper.course_id == course_id)
    template_ids = select(QuestionTemplate.id).where(QuestionTemplate.course_id == course_id)
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

    _bulk_delete_by_course(session, ExamStudyGuideCache, course_id=course_id)
    _bulk_delete_by_course(session, ExamPaper, course_id=course_id)
    _bulk_delete_by_course(session, QuestionTemplate, course_id=course_id)
    _bulk_delete_by_course(session, QuestionTypeRegistry, course_id=course_id)


def _delete_chat_messages(session: Session, *, course_id: str) -> None:
    _bulk_delete_by_course(session, ChatMessage, course_id=course_id)
    _bulk_delete_by_course(session, ChatSession, course_id=course_id)


def _delete_profiles(session: Session, *, course_id: str) -> None:
    _bulk_delete_by_course(session, UserKnowledgeState, course_id=course_id)


def _revoke_course_shares(session: Session, *, course_id: str) -> None:
    now = utcnow()
    shares = session.exec(
        select(CourseShare)
        .where(CourseShare.source_course_id == course_id)
        .where(CourseShare.status != "revoked")
    ).all()
    for share in shares:
        share.status = "revoked"
        share.revoked_at = share.revoked_at or now
        share.updated_at = now
        session.add(share)


def _delete_knowledge_and_curriculum(session: Session, *, course_id: str) -> None:
    session.exec(
        sa.update(KnowledgeDocument)
        .where(KnowledgeDocument.course_id == course_id)
        .values(root_document_id=None, parent_document_id=None)
    )
    session.exec(
        sa.update(KnowledgeUnit)
        .where(KnowledgeUnit.course_id == course_id)
        .values(merged_into_knowledge_unit_id=None)
    )
    _bulk_delete_by_course(session, KnowledgeGraphSourceRef, course_id=course_id)
    _bulk_delete_by_course(session, KnowledgeGraphSyncRun, course_id=course_id)
    _bulk_delete_by_course(session, KnowledgeEdge, course_id=course_id)
    _bulk_delete_by_course(session, KnowledgeDocument, course_id=course_id)
    _bulk_delete_by_course(session, KnowledgeUnit, course_id=course_id)


def _delete_documents_and_chunks(session: Session, *, course_id: str) -> None:
    _bulk_delete_by_course(session, RetrievalChunk, course_id=course_id)


def _clear_course_vector_index_best_effort(course_id: str, *, user_id: str | None) -> None:
    try:
        from app.shared.infra.runtime import is_cloud_mode

        if is_cloud_mode():
            from app.shared.infra.database import get_engine
            from app.shared.infra.course import (
                build_course_index_ref,
                extract_postgres_course_index_data_table_name,
            )

            vector_ref = build_course_index_ref(course_id, owner_user_id=user_id or "local")
            data_table = extract_postgres_course_index_data_table_name(vector_ref)
            if not data_table or not _POSTGRES_IDENTIFIER_RE.fullmatch(data_table):
                return
            with get_engine().begin() as connection:
                connection.execute(sa.text(f"DROP TABLE IF EXISTS public.{data_table}"))
        else:
            from app.shared.infra.search.llamaindex_index import clear_course_index

            clear_course_index(course_id)
    except Exception as exc:  # pragma: no cover - best-effort index cleanup
        logger.warning("course_vector_index_cleanup_failed", course_id=course_id, error=str(exc))


def _delete_planner_records(session: Session, *, course_id: str) -> None:
    del session, course_id


def _delete_raw_files_and_artifacts(session: Session, *, course_id: str, owner_user_id: str) -> None:
    session.exec(
        sa.delete(CourseFileLink)
        .where(
            CourseFileLink.user_id == owner_user_id,
            CourseFileLink.course_id == course_id,
        )
        .execution_options(synchronize_session=False)
    )


def _delete_course_directory(course_id: str, *, user_id: str | None = None) -> None:
    course_dir = build_course_dir(course_id, user_id=user_id)
    if course_dir.exists():
        shutil.rmtree(course_dir, ignore_errors=True)
