from __future__ import annotations

import shutil
from pathlib import Path

import structlog
from sqlmodel import Session, func, select

from app.models import (
    AnswerRecord,
    ChatMessage,
    CurriculumDeriveJob,
    CurriculumSnapshot,
    Document,
    DocumentChunk,
    EdgeRevision,
    EvidenceLink,
    Exam,
    ExamSubmission,
    GraphDigestJob,
    KnowledgeAlias,
    KnowledgeEdge,
    KnowledgeNode,
    KnowledgeRevision,
    Mistake,
    PrereqDagVersion,
    Question,
    RawFile,
    Subject,
    SubjectBuildLock,
    TaxonomyAnchor,
    TeachingUnit,
    TeachingUnitMembership,
    TeachingUnitRevision,
    ThemeTreeNode,
    ThemeTreeVersion,
    UnitDependency,
    UnitTreeMembership,
    UserProfile,
)
from app.repositories.subject_repo import delete_subject
from app.schemas.subject import (
    SubjectDeleteImpactItem,
    SubjectDeletePreviewData,
)
from app.services.knowledge.curriculum_service import clear_subject_knowledge
from app.repositories.knowledge import knowledge_repo
from app.services.upload_support import build_subject_dir

logger = structlog.get_logger()

_EXAM_KEYS = ["exam", "question", "exam_submission", "answer_record", "mistake"]
_KNOWLEDGE_KEYS = [
    "curriculum_derive_job",
    "curriculum_snapshot",
    "edge_revision",
    "evidence_link",
    "graph_digest_job",
    "knowledge_alias",
    "knowledge_edge",
    "knowledge_node",
    "knowledge_revision",
    "prereq_dag_version",
    "subject_build_lock",
    "taxonomy_anchor",
    "teaching_unit",
    "teaching_unit_membership",
    "teaching_unit_revision",
    "theme_tree_node",
    "theme_tree_version",
    "unit_dependency",
    "unit_tree_membership",
]


def _count_query(session: Session, statement) -> int:
    return int(session.exec(statement).one())


def _count_rows(session: Session, model: type, *conditions: object) -> int:
    return _count_query(session, select(func.count()).select_from(model).where(*conditions))


def _sum_counts(counts: dict[str, int], keys: list[str]) -> int:
    return sum(counts.get(key, 0) for key in keys)


def collect_subject_delete_counts(session: Session, *, subject: str) -> dict[str, int]:
    counts = {
        "raw_file": _count_rows(session, RawFile, RawFile.subject == subject),
        "document": _count_rows(session, Document, Document.subject == subject),
        "chat_message": _count_query(
            session,
            select(func.count()).select_from(ChatMessage).where(ChatMessage.subject == subject),
        ),
        "user_profile": _count_query(
            session,
            select(func.count()).select_from(UserProfile).where(UserProfile.subject == subject),
        ),
        "exam": _count_query(
            session,
            select(func.count()).select_from(Exam).where(Exam.subject == subject),
        ),
        "question": _count_query(
            session,
            select(func.count())
            .select_from(Question)
            .join(Exam, Question.exam_id == Exam.id)
            .where(Exam.subject == subject),
        ),
        "exam_submission": _count_query(
            session,
            select(func.count())
            .select_from(ExamSubmission)
            .join(Exam, ExamSubmission.exam_id == Exam.id)
            .where(Exam.subject == subject),
        ),
        "answer_record": _count_query(
            session,
            select(func.count())
            .select_from(AnswerRecord)
            .join(ExamSubmission, AnswerRecord.submission_id == ExamSubmission.id)
            .join(Exam, ExamSubmission.exam_id == Exam.id)
            .where(Exam.subject == subject),
        ),
        "mistake": _count_query(
            session,
            select(func.count())
            .select_from(Mistake)
            .join(AnswerRecord, Mistake.answer_record_id == AnswerRecord.id)
            .join(ExamSubmission, AnswerRecord.submission_id == ExamSubmission.id)
            .join(Exam, ExamSubmission.exam_id == Exam.id)
            .where(Exam.subject == subject),
        ),
        "document_chunk": _count_query(
            session,
            select(func.count())
            .select_from(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.id)
            .where(Document.subject == subject),
        ),
        "curriculum_derive_job": _count_rows(
            session, CurriculumDeriveJob, CurriculumDeriveJob.subject == subject
        ),
        "curriculum_snapshot": _count_rows(
            session, CurriculumSnapshot, CurriculumSnapshot.subject == subject
        ),
        "evidence_link": _count_rows(session, EvidenceLink, EvidenceLink.subject == subject),
        "graph_digest_job": _count_rows(
            session, GraphDigestJob, GraphDigestJob.subject == subject
        ),
        "knowledge_edge": _count_rows(session, KnowledgeEdge, KnowledgeEdge.subject == subject),
        "knowledge_node": _count_rows(session, KnowledgeNode, KnowledgeNode.subject == subject),
        "prereq_dag_version": _count_rows(
            session, PrereqDagVersion, PrereqDagVersion.subject == subject
        ),
        "subject_build_lock": _count_rows(
            session, SubjectBuildLock, SubjectBuildLock.subject == subject
        ),
        "taxonomy_anchor": _count_rows(
            session, TaxonomyAnchor, TaxonomyAnchor.subject == subject
        ),
        "teaching_unit": _count_rows(session, TeachingUnit, TeachingUnit.subject == subject),
        "theme_tree_version": _count_rows(
            session, ThemeTreeVersion, ThemeTreeVersion.subject == subject
        ),
        "knowledge_alias": _count_query(
            session,
            select(func.count())
            .select_from(KnowledgeAlias)
            .join(KnowledgeNode, KnowledgeAlias.node_id == KnowledgeNode.id)
            .where(KnowledgeNode.subject == subject),
        ),
        "knowledge_revision": _count_query(
            session,
            select(func.count())
            .select_from(KnowledgeRevision)
            .join(KnowledgeNode, KnowledgeRevision.node_id == KnowledgeNode.id)
            .where(KnowledgeNode.subject == subject),
        ),
        "edge_revision": _count_query(
            session,
            select(func.count())
            .select_from(EdgeRevision)
            .join(KnowledgeEdge, EdgeRevision.edge_id == KnowledgeEdge.id)
            .where(KnowledgeEdge.subject == subject),
        ),
        "teaching_unit_revision": _count_query(
            session,
            select(func.count())
            .select_from(TeachingUnitRevision)
            .join(TeachingUnit, TeachingUnitRevision.unit_id == TeachingUnit.id)
            .where(TeachingUnit.subject == subject),
        ),
        "teaching_unit_membership": _count_query(
            session,
            select(func.count())
            .select_from(TeachingUnitMembership)
            .join(TeachingUnit, TeachingUnitMembership.unit_id == TeachingUnit.id)
            .where(TeachingUnit.subject == subject),
        ),
        "theme_tree_node": _count_query(
            session,
            select(func.count())
            .select_from(ThemeTreeNode)
            .join(ThemeTreeVersion, ThemeTreeNode.tree_version_id == ThemeTreeVersion.id)
            .where(ThemeTreeVersion.subject == subject),
        ),
        "unit_tree_membership": _count_query(
            session,
            select(func.count())
            .select_from(UnitTreeMembership)
            .join(ThemeTreeVersion, UnitTreeMembership.tree_version_id == ThemeTreeVersion.id)
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
    return counts


def build_subject_delete_preview(
    session: Session,
    *,
    subject: Subject,
) -> SubjectDeletePreviewData:
    detail_counts = collect_subject_delete_counts(session, subject=subject.slug)
    total_related_records = sum(detail_counts.values())
    impact_items = [
        SubjectDeleteImpactItem(
            key="files",
            label="上传文件与解析产物",
            count=detail_counts["raw_file"] + detail_counts["document"] + detail_counts["document_chunk"],
            description="会删除原始文件、解析后的文档和文档切块。",
        ),
        SubjectDeleteImpactItem(
            key="knowledge",
            label="知识图谱与课程结构",
            count=_sum_counts(detail_counts, _KNOWLEDGE_KEYS),
            description="会删除知识点、边、证据、课程结构和构建任务等派生数据。",
        ),
        SubjectDeleteImpactItem(
            key="exam",
            label="试卷与作答记录",
            count=_sum_counts(detail_counts, _EXAM_KEYS),
            description="会删除试卷、题目、提交记录、答案记录和错题分析。",
        ),
        SubjectDeleteImpactItem(
            key="chat",
            label="对话记录",
            count=detail_counts["chat_message"],
            description="会删除该学科下的全部聊天消息。",
        ),
        SubjectDeleteImpactItem(
            key="profile",
            label="学习画像",
            count=detail_counts["user_profile"],
            description="会删除该学科下的掌握度与历史画像记录。",
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


def delete_subject_with_all_content(
    session: Session,
    *,
    subject: Subject,
) -> dict[str, int]:
    counts = collect_subject_delete_counts(session, subject=subject.slug)

    clear_subject_knowledge(session, subject=subject.slug)
    _delete_exam_records(session, subject=subject.slug)
    _delete_chat_messages(session, subject=subject.slug)
    _delete_profiles(session, subject=subject.slug)
    _delete_documents(session, subject=subject.slug)
    _delete_raw_files_and_artifacts(session, subject=subject.slug)
    _delete_subject_directory(subject.slug)
    delete_subject(session, subject)

    deleted_counts = {"subject": 1, **counts}
    logger.info(
        "subject_deleted_with_all_content",
        subject=subject.slug,
        deleted_counts=deleted_counts,
    )
    return deleted_counts


def _delete_exam_records(session: Session, *, subject: str) -> None:
    exams = list(session.exec(select(Exam).where(Exam.subject == subject)).all())
    if not exams:
        return

    exam_ids = [exam.id for exam in exams if exam.id is not None]
    if exam_ids:
        submissions = list(
            session.exec(select(ExamSubmission).where(ExamSubmission.exam_id.in_(exam_ids))).all()
        )
        submission_ids = [submission.id for submission in submissions if submission.id is not None]
        if submission_ids:
            records = list(
                session.exec(
                    select(AnswerRecord).where(AnswerRecord.submission_id.in_(submission_ids))
                ).all()
            )
            record_ids = [record.id for record in records if record.id is not None]
            if record_ids:
                mistakes = list(
                    session.exec(
                        select(Mistake).where(Mistake.answer_record_id.in_(record_ids))
                    ).all()
                )
                for mistake in mistakes:
                    session.delete(mistake)
            for record in records:
                session.delete(record)
        for submission in submissions:
            session.delete(submission)

        questions = list(
            session.exec(select(Question).where(Question.exam_id.in_(exam_ids))).all()
        )
        for question in questions:
            session.delete(question)

    for exam in exams:
        session.delete(exam)
    session.commit()


def _delete_chat_messages(session: Session, *, subject: str) -> None:
    messages = list(session.exec(select(ChatMessage).where(ChatMessage.subject == subject)).all())
    if not messages:
        return
    for message in messages:
        session.delete(message)
    session.commit()


def _delete_profiles(session: Session, *, subject: str) -> None:
    profiles = list(session.exec(select(UserProfile).where(UserProfile.subject == subject)).all())
    if not profiles:
        return
    for profile in profiles:
        session.delete(profile)
    session.commit()


def _delete_documents(session: Session, *, subject: str) -> None:
    documents = list(session.exec(select(Document).where(Document.subject == subject)).all())
    if not documents:
        return

    document_ids = [document.id for document in documents if document.id is not None]
    if document_ids:
        chunks = list(
            session.exec(
                select(DocumentChunk).where(DocumentChunk.document_id.in_(document_ids))
            ).all()
        )
        chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
        if chunk_ids:
            knowledge_repo.delete_embeddings_by_chunk_ids(session, chunk_ids)
        for chunk in chunks:
            session.delete(chunk)
        session.commit()

    for document in documents:
        session.delete(document)
    session.commit()


def _delete_raw_files_and_artifacts(session: Session, *, subject: str) -> None:
    raw_files = list(session.exec(select(RawFile).where(RawFile.subject == subject)).all())
    if not raw_files:
        return

    for raw_file in raw_files:
        for path_value in [raw_file.file_path, raw_file.markdown_path]:
            if path_value:
                Path(path_value).unlink(missing_ok=True)
        if raw_file.asset_dir:
            shutil.rmtree(raw_file.asset_dir, ignore_errors=True)
        session.delete(raw_file)
    session.commit()


def _delete_subject_directory(subject: str) -> None:
    subject_dir = build_subject_dir(subject)
    if subject_dir.exists():
        shutil.rmtree(subject_dir, ignore_errors=True)
