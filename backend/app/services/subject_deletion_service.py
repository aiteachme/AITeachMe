from __future__ import annotations

import shutil

import structlog
from sqlmodel import Session, delete, func, select

from app.models import (
    ChatMessage,
    ChatSession,
    CurriculumDependency,
    CurriculumTreeNode,
    CurriculumUnitLink,
    CurriculumVersion,
    ExamPaper,
    ExamPaperItem,
    KnowledgeAlias,
    KnowledgeDocument,
    KnowledgeEdge,
    KnowledgeEvidence,
    KnowledgeNode,
    QuestionTemplate,
    QuestionTemplateNodeLink,
    RawFile,
    RawFileAsset,
    RetrievalChunk,
    ReviewTask,
    Subject,
    TeachingUnit,
    TeachingUnitMembership,
    UserAnswerAttempt,
    UserKnowledgeState,
)
from app.repositories.subject_repo import delete_subject
from app.schemas.subject import SubjectDeleteImpactItem, SubjectDeletePreviewData
from app.services.upload_support import build_subject_dir

logger = structlog.get_logger()


def _count_model(session: Session, model, *conditions) -> int:
    return int(session.exec(select(func.count()).select_from(model).where(*conditions)).one())


def _count_raw_file_assets(session: Session, *, subject_id: int) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(RawFileAsset)
            .join(RawFile, RawFileAsset.raw_file_id == RawFile.id)
            .where(RawFile.subject_id == subject_id)
        ).one()
    )


def _count_by_node(session: Session, model, *, subject_id: int) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(model)
            .join(KnowledgeNode, model.node_id == KnowledgeNode.id)
            .where(KnowledgeNode.subject_id == subject_id)
        ).one()
    )


def _count_by_unit(session: Session, model, *, subject_id: int) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(model)
            .join(TeachingUnit, model.unit_id == TeachingUnit.id)
            .where(TeachingUnit.subject_id == subject_id)
        ).one()
    )


def _count_by_curriculum(session: Session, model, *, subject_id: int) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(model)
            .join(CurriculumVersion, model.curriculum_version_id == CurriculumVersion.id)
            .where(CurriculumVersion.subject_id == subject_id)
        ).one()
    )


def _count_by_template(session: Session, model, *, subject_id: int) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(model)
            .join(QuestionTemplate, model.question_template_id == QuestionTemplate.id)
            .where(QuestionTemplate.subject_id == subject_id)
        ).one()
    )


def _count_by_exam_paper(session: Session, model, *, subject_id: int) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(model)
            .join(ExamPaper, model.exam_paper_id == ExamPaper.id)
            .where(ExamPaper.subject_id == subject_id)
        ).one()
    )


def _count_by_exam_item(session: Session, model, *, subject_id: int) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(model)
            .join(ExamPaperItem, model.exam_paper_item_id == ExamPaperItem.id)
            .join(ExamPaper, ExamPaperItem.exam_paper_id == ExamPaper.id)
            .where(ExamPaper.subject_id == subject_id)
        ).one()
    )


def collect_subject_delete_counts(session: Session, *, subject: Subject) -> dict[str, int]:
    subject_id = int(subject.id or 0)
    return {
        "raw_file": _count_model(session, RawFile, RawFile.subject_id == subject_id),
        "raw_file_asset": _count_raw_file_assets(session, subject_id=subject_id),
        "retrieval_chunk": _count_model(session, RetrievalChunk, RetrievalChunk.subject_id == subject_id),
        "knowledge_document": _count_model(session, KnowledgeDocument, KnowledgeDocument.subject_id == subject_id),
        "knowledge_node": _count_model(session, KnowledgeNode, KnowledgeNode.subject_id == subject_id),
        "knowledge_alias": _count_by_node(session, KnowledgeAlias, subject_id=subject_id),
        "knowledge_edge": _count_model(session, KnowledgeEdge, KnowledgeEdge.subject_id == subject_id),
        "knowledge_evidence": _count_model(session, KnowledgeEvidence, KnowledgeEvidence.subject_id == subject_id),
        "teaching_unit": _count_model(session, TeachingUnit, TeachingUnit.subject_id == subject_id),
        "teaching_unit_membership": _count_by_unit(session, TeachingUnitMembership, subject_id=subject_id),
        "curriculum_version": _count_model(session, CurriculumVersion, CurriculumVersion.subject_id == subject_id),
        "curriculum_tree_node": _count_by_curriculum(session, CurriculumTreeNode, subject_id=subject_id),
        "curriculum_unit_link": _count_by_curriculum(session, CurriculumUnitLink, subject_id=subject_id),
        "curriculum_dependency": _count_by_curriculum(session, CurriculumDependency, subject_id=subject_id),
        "question_template": _count_model(session, QuestionTemplate, QuestionTemplate.subject_id == subject_id),
        "question_template_node_link": _count_by_template(session, QuestionTemplateNodeLink, subject_id=subject_id),
        "exam_paper": _count_model(session, ExamPaper, ExamPaper.subject_id == subject_id),
        "exam_paper_item": _count_by_exam_paper(session, ExamPaperItem, subject_id=subject_id),
        "user_answer_attempt": _count_by_exam_item(session, UserAnswerAttempt, subject_id=subject_id),
        "user_knowledge_state": _count_model(session, UserKnowledgeState, UserKnowledgeState.subject_id == subject_id),
        "review_task": _count_model(session, ReviewTask, ReviewTask.subject_id == subject_id),
        "chat_message": _count_model(session, ChatMessage, ChatMessage.subject == subject.slug),
        "chat_session": _count_model(session, ChatSession, ChatSession.subject == subject.slug),
    }


def build_subject_delete_preview(
    session: Session,
    *,
    subject: Subject,
) -> SubjectDeletePreviewData:
    detail_counts = collect_subject_delete_counts(session, subject=subject)
    total_related_records = sum(detail_counts.values())
    impact_items = [
        SubjectDeleteImpactItem(
            key="files",
            label="上传文件与解析产物",
            count=detail_counts["raw_file"] + detail_counts["raw_file_asset"] + detail_counts["retrieval_chunk"],
            description="会删除原始文件、提取资源和检索切块。",
        ),
        SubjectDeleteImpactItem(
            key="knowledge",
            label="知识文档与图谱",
            count=(
                detail_counts["knowledge_document"]
                + detail_counts["knowledge_node"]
                + detail_counts["knowledge_alias"]
                + detail_counts["knowledge_edge"]
                + detail_counts["knowledge_evidence"]
            ),
            description="会删除知识文档、知识点、关系和证据。",
        ),
        SubjectDeleteImpactItem(
            key="curriculum",
            label="课程结构",
            count=(
                detail_counts["teaching_unit"]
                + detail_counts["teaching_unit_membership"]
                + detail_counts["curriculum_version"]
                + detail_counts["curriculum_tree_node"]
                + detail_counts["curriculum_unit_link"]
                + detail_counts["curriculum_dependency"]
            ),
            description="会删除教学单元、主题树和先修依赖。",
        ),
        SubjectDeleteImpactItem(
            key="assessment",
            label="测评与学习状态",
            count=(
                detail_counts["question_template"]
                + detail_counts["question_template_node_link"]
                + detail_counts["exam_paper"]
                + detail_counts["exam_paper_item"]
                + detail_counts["user_answer_attempt"]
                + detail_counts["user_knowledge_state"]
                + detail_counts["review_task"]
            ),
            description="会删除题库、试卷、作答结果、掌握度和复习任务。",
        ),
        SubjectDeleteImpactItem(
            key="chat",
            label="对话记录",
            count=detail_counts["chat_message"] + detail_counts["chat_session"],
            description="会删除该学科下的聊天会话和消息。",
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
    counts = collect_subject_delete_counts(session, subject=subject)
    subject_id = int(subject.id or 0)

    session.exec(delete(ChatMessage).where(ChatMessage.subject == subject.slug))
    session.exec(delete(ChatSession).where(ChatSession.subject == subject.slug))

    paper_ids = [int(item) for item in session.exec(select(ExamPaper.id).where(ExamPaper.subject_id == subject_id)).all() if item is not None]
    if paper_ids:
        item_ids = [int(item) for item in session.exec(select(ExamPaperItem.id).where(ExamPaperItem.exam_paper_id.in_(paper_ids))).all() if item is not None]  # type: ignore[union-attr]
        if item_ids:
            session.exec(delete(UserAnswerAttempt).where(UserAnswerAttempt.exam_paper_item_id.in_(item_ids)))  # type: ignore[union-attr]
        session.exec(delete(ExamPaperItem).where(ExamPaperItem.exam_paper_id.in_(paper_ids)))  # type: ignore[union-attr]
        session.exec(delete(ReviewTask).where(ReviewTask.source_exam_paper_id.in_(paper_ids)))  # type: ignore[union-attr]

    template_ids = [int(item) for item in session.exec(select(QuestionTemplate.id).where(QuestionTemplate.subject_id == subject_id)).all() if item is not None]
    if template_ids:
        session.exec(delete(QuestionTemplateNodeLink).where(QuestionTemplateNodeLink.question_template_id.in_(template_ids)))  # type: ignore[union-attr]

    raw_file_ids = [int(item) for item in session.exec(select(RawFile.id).where(RawFile.subject_id == subject_id)).all() if item is not None]
    if raw_file_ids:
        session.exec(delete(RawFileAsset).where(RawFileAsset.raw_file_id.in_(raw_file_ids)))  # type: ignore[union-attr]

    unit_ids = [int(item) for item in session.exec(select(TeachingUnit.id).where(TeachingUnit.subject_id == subject_id)).all() if item is not None]
    if unit_ids:
        session.exec(delete(TeachingUnitMembership).where(TeachingUnitMembership.unit_id.in_(unit_ids)))  # type: ignore[union-attr]

    curriculum_ids = [int(item) for item in session.exec(select(CurriculumVersion.id).where(CurriculumVersion.subject_id == subject_id)).all() if item is not None]
    if curriculum_ids:
        session.exec(delete(CurriculumUnitLink).where(CurriculumUnitLink.curriculum_version_id.in_(curriculum_ids)))  # type: ignore[union-attr]
        session.exec(delete(CurriculumDependency).where(CurriculumDependency.curriculum_version_id.in_(curriculum_ids)))  # type: ignore[union-attr]
        session.exec(delete(CurriculumTreeNode).where(CurriculumTreeNode.curriculum_version_id.in_(curriculum_ids)))  # type: ignore[union-attr]

    node_ids = [int(item) for item in session.exec(select(KnowledgeNode.id).where(KnowledgeNode.subject_id == subject_id)).all() if item is not None]
    if node_ids:
        session.exec(delete(KnowledgeAlias).where(KnowledgeAlias.node_id.in_(node_ids)))  # type: ignore[union-attr]

    edge_ids = [int(item) for item in session.exec(select(KnowledgeEdge.id).where(KnowledgeEdge.subject_id == subject_id)).all() if item is not None]
    if edge_ids:
        session.exec(delete(KnowledgeEvidence).where(KnowledgeEvidence.edge_id.in_(edge_ids)))  # type: ignore[union-attr]
    if node_ids:
        session.exec(delete(KnowledgeEvidence).where(KnowledgeEvidence.node_id.in_(node_ids)))  # type: ignore[union-attr]

    session.exec(delete(RetrievalChunk).where(RetrievalChunk.subject_id == subject_id))
    session.exec(delete(KnowledgeDocument).where(KnowledgeDocument.subject_id == subject_id))
    session.exec(delete(KnowledgeEdge).where(KnowledgeEdge.subject_id == subject_id))
    session.exec(delete(KnowledgeNode).where(KnowledgeNode.subject_id == subject_id))
    session.exec(delete(CurriculumVersion).where(CurriculumVersion.subject_id == subject_id))
    session.exec(delete(TeachingUnit).where(TeachingUnit.subject_id == subject_id))
    session.exec(delete(QuestionTemplate).where(QuestionTemplate.subject_id == subject_id))
    session.exec(delete(ExamPaper).where(ExamPaper.subject_id == subject_id))
    session.exec(delete(UserKnowledgeState).where(UserKnowledgeState.subject_id == subject_id))
    session.exec(delete(ReviewTask).where(ReviewTask.subject_id == subject_id))
    session.exec(delete(RawFile).where(RawFile.subject_id == subject_id))
    session.commit()

    subject_dir = build_subject_dir(subject.slug)
    if subject_dir.exists():
        shutil.rmtree(subject_dir, ignore_errors=True)

    delete_subject(session, subject)
    deleted_counts = {"subject": 1, **counts}
    logger.info("subject_deleted_with_all_content", subject=subject.slug, deleted_counts=deleted_counts)
    return deleted_counts
