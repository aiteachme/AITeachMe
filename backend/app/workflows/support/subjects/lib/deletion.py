from __future__ import annotations

import shutil

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
    ConfirmedBuildPlan,
    ExamPaper,
    ExamPaperItem,
    KnowledgeDocument,
    KnowledgeEdge,
    KnowledgeUnit,
    QuestionTemplate,
    QuestionTypeRegistry,
    RawFile,
    RetrievalChunk,
    Subject,
    UserKnowledgeState,
)
import app.repositories.knowledge.knowledge_repo as knowledge_repo
from app.schemas.subject import SubjectDeleteImpactItem, SubjectDeletePreviewData
from app.utils.path_helpers import build_subject_dir, get_data_dir

logger = structlog.get_logger()

_EXAM_KEYS = [
    "question_template",
    "question_type_registry",
    "exam_paper",
    "exam_paper_item",
]
_PROFILE_KEYS = ["user_knowledge_state"]
_PLANNER_KEYS = ["confirmed_build_plan"]
_KNOWLEDGE_KEYS = [
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


def _bulk_delete_by_subject(session: Session, model: type, *, subject: str) -> None:
    session.exec(sa.delete(model).where(model.subject == subject))


def collect_subject_delete_counts(session: Session, *, subject: str) -> dict[str, int]:
    return {
        "raw_file": _count_rows(session, RawFile, RawFile.subject == subject),
        "retrieval_chunk": _count_rows(session, RetrievalChunk, RetrievalChunk.subject == subject),
        "knowledge_document": _count_rows(
            session,
            KnowledgeDocument,
            KnowledgeDocument.subject == subject,
        ),
        "chat_message": _count_rows(session, ChatMessage, ChatMessage.subject == subject),
        "chat_session": _count_rows(session, ChatSession, ChatSession.subject == subject),
        "question_template": _count_rows(session, QuestionTemplate, QuestionTemplate.subject == subject),
        "question_type_registry": _count_rows(session, QuestionTypeRegistry, QuestionTypeRegistry.subject == subject),
        "exam_paper": _count_rows(session, ExamPaper, ExamPaper.subject == subject),
        "exam_paper_item": _count_query(
            session,
            select(func.count())
            .select_from(ExamPaperItem)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(ExamPaper.subject == subject),
        ),
        "user_knowledge_state": _count_rows(session, UserKnowledgeState, UserKnowledgeState.subject == subject),
        "knowledge_edge": _count_rows(session, KnowledgeEdge, KnowledgeEdge.subject == subject),
        "knowledge_unit": _count_rows(session, KnowledgeUnit, KnowledgeUnit.subject == subject),
        "confirmed_build_plan": _count_rows(session, ConfirmedBuildPlan, ConfirmedBuildPlan.subject == subject),
    }


def build_subject_delete_preview(session: Session, *, subject: Subject) -> SubjectDeletePreviewData:
    detail_counts = collect_subject_delete_counts(session, subject=subject.slug)
    total_related_records = sum(detail_counts.values())
    impact_items = [
        SubjectDeleteImpactItem(
            key="files",
            label="上传文件与切块",
            count=detail_counts["raw_file"] + detail_counts["retrieval_chunk"],
            description="会删除原始文件记录、切块与向量索引。",
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
        SubjectDeleteImpactItem(
            key="planner",
            label="构建方案",
            count=_sum_counts(detail_counts, _PLANNER_KEYS),
            description="会删除该学科已确认的构建方案。",
        ),
    ]
    return SubjectDeletePreviewData(
        subject_id=subject.slug,
        subject_name=subject.name,
        has_content=total_related_records > 0,
        total_related_records=total_related_records,
        impact_items=[item for item in impact_items if item.count > 0],
        detail_counts=detail_counts,
    )


def delete_subject_with_all_content(session: Session, *, subject: Subject) -> dict[str, int]:
    subject_slug = subject.slug
    owner_user_id = subject.user_id
    counts = collect_subject_delete_counts(session, subject=subject_slug)
    try:
        _delete_profiles(session, subject=subject_slug)
        _delete_exam_records(session, subject=subject_slug)
        _delete_chat_messages(session, subject=subject_slug)
        _delete_knowledge_and_curriculum(session, subject=subject_slug)
        _delete_documents_and_chunks(session, subject=subject_slug)
        _delete_planner_records(session, subject=subject_slug)
        _delete_raw_files_and_artifacts(session, subject=subject_slug)
        session.delete(subject)
        session.commit()
    except Exception:
        session.rollback()
        raise

    _delete_subject_artifacts_best_effort(subject_slug, user_id=owner_user_id)
    deleted_counts = {"subject": 1, **counts}
    logger.info("subject_deleted_with_all_content", subject=subject_slug, deleted_counts=deleted_counts)
    return deleted_counts


async def delete_subject_artifacts_async(subject_slug: str, *, user_id: str | None = None) -> None:
    """Delete all stored files for one subject through ContentStore."""

    cs = get_content_store()
    scope = (
        build_subject_storage_scope(user_id=user_id, subject=subject_slug)
        if user_id
        else resolve_subject_storage_scope(subject_slug)
    )
    await cs.delete_prefix(scope.subject_prefix())
    # Also clean local runtime directories when present.
    _delete_subject_directory(subject_slug, user_id=user_id)


def _delete_subject_artifacts_best_effort(subject_slug: str, *, user_id: str | None) -> None:
    cs = get_content_store()
    try:
        scope = build_subject_storage_scope(user_id=user_id or "local", subject=subject_slug)
        run_store_sync(cs.delete_prefix, scope.subject_prefix(), default=0)
    except Exception as exc:  # pragma: no cover - best-effort cleanup
        logger.warning("subject_artifact_prefix_cleanup_failed", subject=subject_slug, error=str(exc))
    _delete_subject_directory(subject_slug, user_id=user_id)


def _delete_exam_records(session: Session, *, subject: str) -> None:
    paper_items = list(
        session.exec(
            select(ExamPaperItem)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(ExamPaper.subject == subject)
        ).all()
    )
    papers = list(session.exec(select(ExamPaper).where(ExamPaper.subject == subject)).all())
    templates = list(session.exec(select(QuestionTemplate).where(QuestionTemplate.subject == subject)).all())

    for item in paper_items:
        session.delete(item)

    for paper in papers:
        session.delete(paper)

    for template in templates:
        session.delete(template)

    registry_items = list(
        session.exec(select(QuestionTypeRegistry).where(QuestionTypeRegistry.subject == subject)).all()
    )
    for registry_item in registry_items:
        session.delete(registry_item)


def _delete_chat_messages(session: Session, *, subject: str) -> None:
    messages = list(session.exec(select(ChatMessage).where(ChatMessage.subject == subject)).all())
    for message in messages:
        session.delete(message)

    sessions = list(session.exec(select(ChatSession).where(ChatSession.subject == subject)).all())
    for item in sessions:
        session.delete(item)


def _delete_profiles(session: Session, *, subject: str) -> None:
    knowledge_states = list(
        session.exec(select(UserKnowledgeState).where(UserKnowledgeState.subject == subject)).all()
    )
    for state in knowledge_states:
        session.delete(state)


def _delete_knowledge_and_curriculum(session: Session, *, subject: str) -> None:
    for model in (
        KnowledgeDocument,
        KnowledgeEdge,
        KnowledgeUnit,
    ):
        _bulk_delete_by_subject(session, model, subject=subject)


def _delete_documents_and_chunks(session: Session, *, subject: str) -> None:
    chunks = list(session.exec(select(RetrievalChunk).where(RetrievalChunk.subject == subject)).all())
    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    if chunk_ids:
        knowledge_repo.delete_embeddings_by_chunk_ids(session, subject=subject, chunk_ids=chunk_ids)
    for chunk in chunks:
        session.delete(chunk)


def _delete_planner_records(session: Session, *, subject: str) -> None:
    plans = list(session.exec(select(ConfirmedBuildPlan).where(ConfirmedBuildPlan.subject == subject)).all())
    for plan in plans:
        session.delete(plan)


def _delete_raw_files_and_artifacts(session: Session, *, subject: str) -> None:
    raw_files = list(session.exec(select(RawFile).where(RawFile.subject == subject)).all())
    if not raw_files:
        return

    for raw_file in raw_files:
        session.delete(raw_file)


def _delete_subject_directory(subject: str, *, user_id: str | None = None) -> None:
    subject_dirs = {
        build_subject_dir(subject, user_id=user_id),
        get_data_dir() / subject,  # Best-effort cleanup for legacy top-level folders.
    }
    for subject_dir in subject_dirs:
        if subject_dir.exists():
            shutil.rmtree(subject_dir, ignore_errors=True)
