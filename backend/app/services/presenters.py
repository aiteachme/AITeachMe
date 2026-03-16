"""Helpers for mapping persistence models into API response schemas."""

from __future__ import annotations

from typing import Any, Mapping

from app.repositories.models import ChatMessage, DocSet, Document, RawFile, UserProfile
from app.schemas.chat import ChatHistoryResponse, ChatMessageItem
from app.schemas.exam import (
    AnswerResultItem,
    ExamHistoryItem,
    ExamHistoryResponse,
    ExamResponse,
    QuestionItem,
    SubmitResponse,
)
from app.schemas.knowledge import (
    DocumentItem,
    DocumentTreeItem,
    KnowledgeGetResponse,
    KnowledgeListResponse,
    KnowledgeTreeResponse,
    DocSetListItem,
    OutlineNode,
)
from app.schemas.profile import (
    MistakeItem,
    ProfileListResponse,
    ProfileMistakesResponse,
    ReportResponse,
    ProfileItem,
)
from app.schemas.upload import FileGetResponse, FileItem, FileListResponse, FileStatusResponse


def require_id(value: int | None, field_name: str) -> int:
    if value is None:
        raise ValueError(f"{field_name} is unexpectedly None for a persisted record")
    return value


def to_file_item(raw_file: RawFile) -> FileItem:
    return FileItem(
        id=require_id(raw_file.id, "RawFile.id"),
        filename=raw_file.filename,
        filetype=raw_file.filetype,
        parse_status=raw_file.parse_status,
        markdown_ready=bool(raw_file.markdown_path),
        latest_updated_at=raw_file.updated_at,
        created_at=raw_file.created_at,
    )


def to_file_list_response(items: list[RawFile], total: int) -> FileListResponse:
    return FileListResponse(items=[to_file_item(item) for item in items], total=total)


def to_file_status_response(raw_file: RawFile) -> FileStatusResponse:
    return FileStatusResponse(
        file_id=require_id(raw_file.id, "RawFile.id"),
        upload_status="uploaded",
        parse_status=raw_file.parse_status,
        markdown_ready=bool(raw_file.markdown_path),
        asset_ready=bool(raw_file.asset_dir),
        error=raw_file.parse_error,
        latest_updated_at=raw_file.updated_at,
    )


def to_file_get_response(
    raw_file: RawFile,
    *,
    markdown_content: str,
    assets: list[dict[str, str]],
) -> FileGetResponse:
    return FileGetResponse(
        file_id=require_id(raw_file.id, "RawFile.id"),
        filename=raw_file.filename,
        parse_status=raw_file.parse_status,
        markdown_content=markdown_content,
        assets=assets,
    )


def to_outline_node_tree(nodes: list[OutlineNode]) -> list[OutlineNode]:
    return nodes


def to_document_item(document: Document) -> DocumentItem:
    return DocumentItem(
        id=require_id(document.id, "Document.id"),
        source_file_id=document.source_file_id,
        title=document.title,
        markdown_content=document.markdown_content,
        pipeline_stage=document.pipeline_stage,
    )


def to_doc_set_list_item(doc_set: DocSet, documents_count: int) -> DocSetListItem:
    return DocSetListItem(
        id=require_id(doc_set.id, "DocSet.id"),
        title=doc_set.title,
        description=doc_set.description,
        build_status=doc_set.build_status,
        documents_count=documents_count,
        created_at=doc_set.created_at,
        updated_at=doc_set.updated_at,
    )


def to_knowledge_list_response(
    items: list[DocSet],
    total: int,
    documents_count_by_id: Mapping[int, int],
) -> KnowledgeListResponse:
    return KnowledgeListResponse(
        items=[
            to_doc_set_list_item(item, documents_count_by_id.get(require_id(item.id, "DocSet.id"), 0))
            for item in items
        ],
        total=total,
    )


def to_knowledge_get_response(doc_set: DocSet, documents: list[Document]) -> KnowledgeGetResponse:
    return KnowledgeGetResponse(
        docset_id=require_id(doc_set.id, "DocSet.id"),
        title=doc_set.title,
        description=doc_set.description,
        build_status=doc_set.build_status,
        documents=[to_document_item(document) for document in documents],
    )


def to_document_tree_item(document: Document, nodes: list[OutlineNode]) -> DocumentTreeItem:
    return DocumentTreeItem(
        document_id=require_id(document.id, "Document.id"),
        title=document.title,
        nodes=to_outline_node_tree(nodes),
    )


def to_knowledge_tree_response(
    doc_set: DocSet,
    document_nodes: list[tuple[Document, list[OutlineNode]]],
) -> KnowledgeTreeResponse:
    return KnowledgeTreeResponse(
        docset_id=require_id(doc_set.id, "DocSet.id"),
        title=doc_set.title,
        documents=[to_document_tree_item(document, nodes) for document, nodes in document_nodes],
    )


def to_chat_message_item(message: ChatMessage) -> ChatMessageItem:
    return ChatMessageItem(
        id=require_id(message.id, "ChatMessage.id"),
        turn_id=message.turn_id,
        role=message.role,
        content=message.content,
        contexts=message.contexts,
        created_at=message.created_at,
    )


def to_chat_history_response(items: list[ChatMessage], total: int) -> ChatHistoryResponse:
    return ChatHistoryResponse(items=[to_chat_message_item(item) for item in items], total=total)


def to_question_item(question: Any) -> QuestionItem:
    return QuestionItem(
        question_key=question.question_key,
        type=question.type,
        stem=question.stem,
        options=question.options,
        knowledge_point=question.knowledge_point,
        difficulty=question.difficulty,
    )


def to_exam_response(exam_id: int | None, questions: list[Any]) -> ExamResponse:
    return ExamResponse(
        exam_id=require_id(exam_id, "Exam.id"),
        questions=[to_question_item(question) for question in questions],
    )


def to_answer_result_item(
    *,
    question_key: str,
    is_correct: bool,
    user_answer: str,
    correct_answer: str,
    explanation: str,
    analysis: str | None,
) -> AnswerResultItem:
    return AnswerResultItem(
        question_key=question_key,
        is_correct=is_correct,
        user_answer=user_answer,
        correct_answer=correct_answer,
        explanation=explanation,
        analysis=analysis,
    )


def to_submit_response(
    submission_id: int | None,
    score: float,
    results: list[AnswerResultItem],
) -> SubmitResponse:
    return SubmitResponse(
        submission_id=require_id(submission_id, "ExamSubmission.id"),
        score=score,
        results=results,
    )


def to_exam_history_item(item: Mapping[str, Any]) -> ExamHistoryItem:
    return ExamHistoryItem(
        exam_id=item["exam_id"],
        submission_id=item.get("submission_id"),
        score=item.get("score"),
        created_at=item["created_at"],
    )


def to_exam_history_response(items: list[Mapping[str, Any]], total: int) -> ExamHistoryResponse:
    return ExamHistoryResponse(items=[to_exam_history_item(item) for item in items], total=total)


def to_profile_item(profile: UserProfile) -> ProfileItem:
    return ProfileItem(
        knowledge_point=profile.knowledge_point,
        mastery=profile.mastery,
        attempts=profile.attempts,
        correct=profile.correct,
    )


def to_profile_response(items: list[UserProfile], total: int) -> ProfileListResponse:
    return ProfileListResponse(items=[to_profile_item(item) for item in items], total=total)


def to_report_response(report: Mapping[str, Any]) -> ReportResponse:
    return ReportResponse(
        overall_mastery=report["overall_mastery"],
        weak_points_top5=[to_profile_item(item) for item in report["weak_points_top5"]],
        suggestions=report["suggestions"],
    )


def to_mistake_item(item: Mapping[str, Any]) -> MistakeItem:
    return MistakeItem(
        id=item["id"],
        question_stem=item["question_stem"],
        question_type=item["question_type"],
        user_answer=item["user_answer"],
        correct_answer=item["correct_answer"],
        analysis=item["analysis"],
        knowledge_point=item["knowledge_point"],
        created_at=item["created_at"],
    )


def to_mistake_list_response(items: list[Mapping[str, Any]], total: int) -> ProfileMistakesResponse:
    return ProfileMistakesResponse(items=[to_mistake_item(item) for item in items], total=total)
