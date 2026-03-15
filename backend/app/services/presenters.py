"""Helpers for mapping repository/domain models into API response schemas."""

from __future__ import annotations

from typing import Any, Mapping

from app.repositories.models import ChatMessage, Knowledge, RawFile, UserProfile
from app.schemas.chat import ChatHistoryResponse, ChatMessageItem
from app.schemas.exam import AnswerResultItem, ExamHistoryItem, ExamHistoryResponse, ExamResponse, QuestionItem, SubmitResponse
from app.schemas.knowledge import DocumentItem, DocumentListResponse, OutlineNode, OutlineResponse
from app.schemas.profile import MistakeItem, MistakeListResponse, ProfileItem, ProfileResponse, ReportResponse
from app.schemas.upload import FileItem, FileListResponse


def require_id(value: int | None, field_name: str) -> int:
    """Return a persisted integer identifier or raise a descriptive error."""

    if value is None:
        raise ValueError(f"{field_name} is unexpectedly None for a persisted record")
    return value


def to_file_item(raw_file: RawFile) -> FileItem:
    """Convert a `RawFile` ORM object into an API file-list item."""

    return FileItem(
        id=require_id(raw_file.id, "RawFile.id"),
        filename=raw_file.filename,
        filetype=raw_file.filetype,
        parse_status=raw_file.parse_status,
        created_at=raw_file.created_at,
    )


def to_file_list_response(items: list[RawFile], total: int) -> FileListResponse:
    """Build a paginated file list response."""

    return FileListResponse(items=[to_file_item(item) for item in items], total=total)


def to_outline_node_tree(nodes: list[OutlineNode]) -> list[OutlineNode]:
    """Identity helper used to keep outline response assembly explicit."""

    return nodes


def to_outline_response(knowledge: Knowledge, nodes: list[OutlineNode]) -> OutlineResponse:
    """Build a knowledge outline response for one document."""

    return OutlineResponse(
        knowledge_id=require_id(knowledge.id, "Knowledge.id"),
        title=knowledge.title,
        nodes=to_outline_node_tree(nodes),
    )


def to_document_item(knowledge: Knowledge) -> DocumentItem:
    """Convert a `Knowledge` ORM object into a document list item."""

    return DocumentItem(
        id=require_id(knowledge.id, "Knowledge.id"),
        title=knowledge.title,
        markdown_content=knowledge.markdown_content,
        pipeline_stage=knowledge.pipeline_stage,
    )


def to_document_list_response(items: list[Knowledge], total: int) -> DocumentListResponse:
    """Build a paginated knowledge document response."""

    return DocumentListResponse(items=[to_document_item(item) for item in items], total=total)


def to_chat_message_item(message: ChatMessage) -> ChatMessageItem:
    """Convert a `ChatMessage` ORM object into a chat history item."""

    return ChatMessageItem(
        id=require_id(message.id, "ChatMessage.id"),
        turn_id=message.turn_id,
        role=message.role,
        content=message.content,
        contexts=message.contexts,
        created_at=message.created_at,
    )


def to_chat_history_response(items: list[ChatMessage], total: int) -> ChatHistoryResponse:
    """Build a paginated chat history response."""

    return ChatHistoryResponse(items=[to_chat_message_item(item) for item in items], total=total)


def to_question_item(question: Any) -> QuestionItem:
    """Convert an exam question ORM object into the public DTO."""

    return QuestionItem(
        question_key=question.question_key,
        type=question.type,
        stem=question.stem,
        options=question.options,
        knowledge_point=question.knowledge_point,
        difficulty=question.difficulty,
    )


def to_exam_response(exam_id: int | None, questions: list[Any]) -> ExamResponse:
    """Build an exam generation response without exposing correct answers."""

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
    """Create a single answer-result DTO."""

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
    """Build the final submit response DTO."""

    return SubmitResponse(
        submission_id=require_id(submission_id, "ExamSubmission.id"),
        score=score,
        results=results,
    )


def to_exam_history_item(item: Mapping[str, Any]) -> ExamHistoryItem:
    """Convert a repository exam-history row mapping into its response DTO."""

    return ExamHistoryItem(
        exam_id=item["exam_id"],
        submission_id=item.get("submission_id"),
        score=item.get("score"),
        created_at=item["created_at"],
    )


def to_exam_history_response(items: list[Mapping[str, Any]], total: int) -> ExamHistoryResponse:
    """Build a paginated exam history response."""

    return ExamHistoryResponse(items=[to_exam_history_item(item) for item in items], total=total)


def to_profile_item(profile: UserProfile) -> ProfileItem:
    """Convert a `UserProfile` ORM object into a profile response item."""

    return ProfileItem(
        knowledge_point=profile.knowledge_point,
        mastery=profile.mastery,
        attempts=profile.attempts,
        correct=profile.correct,
    )


def to_profile_response(items: list[UserProfile], total: int) -> ProfileResponse:
    """Build a paginated profile response."""

    return ProfileResponse(items=[to_profile_item(item) for item in items], total=total)


def to_report_response(report: Mapping[str, Any]) -> ReportResponse:
    """Convert an aggregated report mapping into the public report schema."""

    return ReportResponse(
        overall_mastery=report["overall_mastery"],
        weak_points_top5=[to_profile_item(item) for item in report["weak_points_top5"]],
        suggestions=report["suggestions"],
    )


def to_mistake_item(item: Mapping[str, Any]) -> MistakeItem:
    """Convert a repository mistake row into its API DTO."""

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


def to_mistake_list_response(items: list[Mapping[str, Any]], total: int) -> MistakeListResponse:
    """Build a paginated mistake-book response."""

    return MistakeListResponse(items=[to_mistake_item(item) for item in items], total=total)
