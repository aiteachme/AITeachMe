from __future__ import annotations

import shutil
from pathlib import Path

import structlog
from sqlmodel import Session, func, select

from app.models import (
    ChatMessage,
    ChatSession,
    CurriculumVersion,
    ExamPaper,
    ExamPaperItem,
    KnowledgeDocument,
    KnowledgeEdge,
    KnowledgeNode,
    PrereqDagVersion,
    QuestionTemplate,
    RawFile,
    RetrievalChunk,
    Subject,
    TaxonomyAnchor,
    TeachingUnit,
    ThemeTreeNode,
    ThemeTreeVersion,
    UnitDependency,
    UserKnowledgeState,
)
from app.repositories.knowledge import knowledge_repo
from app.repositories.subject_repo import delete_subject
from app.schemas.subject import SubjectDeleteImpactItem, SubjectDeletePreviewData
from app.services.upload_support import build_asset_name_prefix, build_subject_dir, delete_asset_files

logger = structlog.get_logger()

_EXAM_KEYS = [
    "question_template",
    "exam_paper",
    "exam_paper_item",
]
_PROFILE_KEYS = ["user_knowledge_state"]
_KNOWLEDGE_KEYS = [
    "curriculum_version",
    "knowledge_document",
    "knowledge_edge",
    "knowledge_node",
    "prereq_dag_version",
    "taxonomy_anchor",
    "teaching_unit",
    "theme_tree_node",
    "theme_tree_version",
    "unit_dependency",
]


def _count_query(session: Session, statement) -> int:
    return int(session.exec(statement).one())


def _count_rows(session: Session, model: type, *conditions: object) -> int:
    return _count_query(session, select(func.count()).select_from(model).where(*conditions))


def _sum_counts(counts: dict[str, int], keys: list[str]) -> int:
    return sum(counts.get(key, 0) for key in keys)


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
        "exam_paper": _count_rows(session, ExamPaper, ExamPaper.subject == subject),
        "exam_paper_item": _count_query(
            session,
            select(func.count())
            .select_from(ExamPaperItem)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(ExamPaper.subject == subject),
        ),
        "user_knowledge_state": _count_rows(session, UserKnowledgeState, UserKnowledgeState.subject == subject),
        "curriculum_version": _count_rows(session, CurriculumVersion, CurriculumVersion.subject == subject),
        "knowledge_edge": _count_rows(session, KnowledgeEdge, KnowledgeEdge.subject == subject),
        "knowledge_node": _count_rows(session, KnowledgeNode, KnowledgeNode.subject == subject),
        "prereq_dag_version": _count_rows(session, PrereqDagVersion, PrereqDagVersion.subject == subject),
        "taxonomy_anchor": _count_rows(session, TaxonomyAnchor, TaxonomyAnchor.subject == subject),
        "teaching_unit": _count_rows(session, TeachingUnit, TeachingUnit.subject == subject),
        "theme_tree_version": _count_rows(session, ThemeTreeVersion, ThemeTreeVersion.subject == subject),
        "theme_tree_node": _count_query(
            session,
            select(func.count())
            .select_from(ThemeTreeNode)
            .join(ThemeTreeVersion, ThemeTreeNode.tree_version_id == ThemeTreeVersion.id)
            .where(ThemeTreeVersion.subject == subject),
        ),
        "unit_dependency": _count_query(
            session,
            select(func.count())
            .select_from(UnitDependency)
            .join(PrereqDagVersion, UnitDependency.dag_version_id == PrereqDagVersion.id)
            .where(PrereqDagVersion.subject == subject),
        ),
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
    counts = collect_subject_delete_counts(session, subject=subject.slug)
    _delete_exam_records(session, subject=subject.slug)
    _delete_chat_messages(session, subject=subject.slug)
    _delete_profiles(session, subject=subject.slug)
    _delete_knowledge_and_curriculum(session, subject=subject.slug)
    _delete_documents_and_chunks(session, subject=subject.slug)
    _delete_raw_files_and_artifacts(session, subject=subject.slug)
    _delete_subject_directory(subject.slug)
    delete_subject(session, subject)

    deleted_counts = {"subject": 1, **counts}
    logger.info("subject_deleted_with_all_content", subject=subject.slug, deleted_counts=deleted_counts)
    return deleted_counts


def _delete_exam_records(session: Session, *, subject: str) -> None:
    paper_items = list(
        session.exec(
            select(ExamPaperItem)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(ExamPaper.subject == subject)
        ).all()
    )
    for item in paper_items:
        session.delete(item)

    papers = list(session.exec(select(ExamPaper).where(ExamPaper.subject == subject)).all())
    for paper in papers:
        session.delete(paper)

    templates = list(session.exec(select(QuestionTemplate).where(QuestionTemplate.subject == subject)).all())
    for template in templates:
        session.delete(template)

    session.commit()


def _delete_chat_messages(session: Session, *, subject: str) -> None:
    messages = list(session.exec(select(ChatMessage).where(ChatMessage.subject == subject)).all())
    for message in messages:
        session.delete(message)

    sessions = list(session.exec(select(ChatSession).where(ChatSession.subject == subject)).all())
    for item in sessions:
        session.delete(item)

    if messages or sessions:
        session.commit()


def _delete_profiles(session: Session, *, subject: str) -> None:
    knowledge_states = list(
        session.exec(select(UserKnowledgeState).where(UserKnowledgeState.subject == subject)).all()
    )
    for state in knowledge_states:
        session.delete(state)

    if knowledge_states:
        session.commit()


def _delete_knowledge_and_curriculum(session: Session, *, subject: str) -> None:
    knowledge_documents = list(
        session.exec(select(KnowledgeDocument).where(KnowledgeDocument.subject == subject)).all()
    )
    for item in knowledge_documents:
        session.delete(item)

    tree_versions = list(session.exec(select(ThemeTreeVersion).where(ThemeTreeVersion.subject == subject)).all())
    tree_version_ids = [item.id for item in tree_versions if item.id is not None]
    if tree_version_ids:
        tree_nodes = list(
            session.exec(
                select(ThemeTreeNode).where(ThemeTreeNode.tree_version_id.in_(tree_version_ids))
            ).all()
        )
        for item in tree_nodes:
            session.delete(item)

    dag_versions = list(session.exec(select(PrereqDagVersion).where(PrereqDagVersion.subject == subject)).all())
    dag_version_ids = [item.id for item in dag_versions if item.id is not None]
    if dag_version_ids:
        dependencies = list(
            session.exec(
                select(UnitDependency).where(UnitDependency.dag_version_id.in_(dag_version_ids))
            ).all()
        )
        for item in dependencies:
            session.delete(item)

    units = list(session.exec(select(TeachingUnit).where(TeachingUnit.subject == subject)).all())
    curriculum_versions = list(
        session.exec(select(CurriculumVersion).where(CurriculumVersion.subject == subject)).all()
    )
    anchors = list(session.exec(select(TaxonomyAnchor).where(TaxonomyAnchor.subject == subject)).all())
    edges = list(session.exec(select(KnowledgeEdge).where(KnowledgeEdge.subject == subject)).all())
    nodes = list(session.exec(select(KnowledgeNode).where(KnowledgeNode.subject == subject)).all())

    for item in curriculum_versions + tree_versions + dag_versions + anchors + edges + nodes + units:
        session.delete(item)

    session.commit()


def _delete_documents_and_chunks(session: Session, *, subject: str) -> None:
    chunks = list(session.exec(select(RetrievalChunk).where(RetrievalChunk.subject == subject)).all())
    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    if chunk_ids:
        knowledge_repo.delete_embeddings_by_chunk_ids(session, chunk_ids)
    for chunk in chunks:
        session.delete(chunk)
    if chunks:
        session.commit()


def _delete_raw_files_and_artifacts(session: Session, *, subject: str) -> None:
    raw_files = list(session.exec(select(RawFile).where(RawFile.subject == subject)).all())
    if not raw_files:
        return

    for raw_file in raw_files:
        for path_value in [raw_file.file_path, raw_file.markdown_path]:
            if path_value:
                Path(path_value).unlink(missing_ok=True)
        delete_asset_files(
            raw_file.asset_dir,
            asset_name_prefix=build_asset_name_prefix(
                filename=raw_file.filename,
                file_uid=raw_file.uid,
                file_id=raw_file.id,
            ),
        )
        session.delete(raw_file)
    session.commit()


def _delete_subject_directory(subject: str) -> None:
    subject_dir = build_subject_dir(subject)
    if subject_dir.exists():
        shutil.rmtree(subject_dir, ignore_errors=True)
