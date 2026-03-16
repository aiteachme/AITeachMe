"""Subject-scoped exam routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.core.exceptions import ExamNotFoundError
from app.repositories import exam_repo
from app.schemas.exam import (
    AnswerResultItem,
    ExamHistoryResponse,
    ExamListRequest,
    ExamMakeRequest,
    ExamResponse,
    ExamSubmitRequest,
    SubmitResponse,
)
from app.services.exam_service import create_exam, submit_exam
from app.services.presenters import (
    to_answer_result_item,
    to_exam_history_response,
    to_exam_response,
    to_submit_response,
)
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/exam", tags=["exam"])


@router.post(
    "/make",
    response_model=ExamResponse,
    summary="Generate an exam",
    description="Generate a new exam for the selected subject.",
    response_description="Generated exam.",
    responses=build_error_responses([400, 404, 500, 502, 503]),
)
async def make_exam(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: ExamMakeRequest = Body(...),
    session: Session = Depends(get_db),
) -> ExamResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)

    exam, questions = await create_exam(
        session,
        subject=normalized_subject,
        num_questions=body.num,
        knowledge_points=body.points,
    )
    return to_exam_response(exam.id, questions)


@router.post(
    "/submit",
    response_model=SubmitResponse,
    summary="Submit exam answers",
    description="Submit answers for an existing exam under the selected subject.",
    response_description="Grading summary.",
    responses=build_error_responses([400, 404, 500, 502, 503]),
)
async def submit_exam_answers(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: ExamSubmitRequest = Body(...),
    session: Session = Depends(get_db),
) -> SubmitResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)

    exam = exam_repo.get_exam_by_id(session, body.exam_id)
    if exam is None or exam.subject != normalized_subject:
        raise ExamNotFoundError(body.exam_id)

    answers_dict = {answer.question_key: answer.answer for answer in body.answers}
    submission, records, mistakes, questions = await submit_exam(
        session,
        exam_id=body.exam_id,
        answers=answers_dict,
    )

    question_by_id = {question.id: question for question in questions}
    mistake_by_record_id = {mistake.answer_record_id: mistake for mistake in mistakes}

    results: list[AnswerResultItem] = []
    for record in records:
        question = question_by_id.get(record.question_id)
        mistake = mistake_by_record_id.get(record.id)
        results.append(
            to_answer_result_item(
                question_key=question.question_key if question is not None else "",
                is_correct=record.is_correct,
                user_answer=record.user_answer,
                correct_answer=question.answer if question is not None else "",
                explanation=question.explanation if question is not None else "",
                analysis=mistake.analysis if mistake is not None else None,
            )
        )

    return to_submit_response(submission.id, submission.score, results)


@router.post(
    "/list",
    response_model=ExamHistoryResponse,
    summary="List exam history",
    description="Return paginated exam history for one subject.",
    response_description="Paginated exam history.",
    responses=build_error_responses([400, 404, 500]),
)
async def list_exams(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: ExamListRequest = Body(default=ExamListRequest()),
    session: Session = Depends(get_db),
) -> ExamHistoryResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)

    items, total = exam_repo.list_exam_history_by_subject(
        session,
        normalized_subject,
        limit=body.limit,
        offset=body.offset,
    )
    return to_exam_history_response(items, total)
