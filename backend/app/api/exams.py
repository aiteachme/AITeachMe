"""Exam API endpoints."""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, Path, Query
from sqlmodel import Session

from app.api.deps import CurrentUserContext, get_current_user_context, get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, PaginatedData, build_paginated_data, ok_response
from app.schemas.exams import (
    ExamGenerateJobStatusResponse,
    ExamGenerateRequest,
    ExamGradeJobStatusResponse,
    ExamHistoryItem,
    ExamPaperDeleteResponse,
    ExamPaperDetailResponse,
    ExamPaperItemResponse,
    ExamSubmitRequest,
    QuestionBankItemResponse,
)
from app.services.exams_service import (
    ExamPaperDetail,
    QuestionBankItem,
    delete_exam_paper,
    get_exam_generate_job_status,
    get_exam_grade_job_status,
    get_exam_history,
    get_exam_paper_detail,
    get_question_bank,
    submit_exam_answers,
    trigger_exam_generate,
    trigger_exam_grade,
)
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/exams", tags=["exams"])


def _parse_json_list(raw: str | None) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def _to_exam_generate_job_response(job) -> ExamGenerateJobStatusResponse:
    return ExamGenerateJobStatusResponse(
        id=job.id or 0,
        status=job.status,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        subject=job.subject,
        user_id=job.user_id,
        exam_mode=job.exam_mode,
        num_questions=job.num_questions,
        exam_paper_id=job.exam_paper_id,
        theme_tree_node_id=job.theme_tree_node_id,
        teaching_unit_ids=[int(item) for item in _parse_json_list(job.teaching_unit_ids_json)],
    )


def _to_exam_grade_job_response(job) -> ExamGradeJobStatusResponse:
    return ExamGradeJobStatusResponse(
        id=job.id or 0,
        status=job.status,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
        exam_paper_id=job.exam_paper_id,
        score=job.score,
        states_updated=job.states_updated,
        tasks_created=job.tasks_created,
        mastery_consumed=job.mastery_consumed,
    )


def _to_exam_history_item(paper) -> ExamHistoryItem:
    return ExamHistoryItem(
        id=int(paper["id"]),
        subject=str(paper["subject"]),
        user_id=str(paper["user_id"]),
        exam_mode=str(paper["exam_mode"]),
        status=str(paper["status"]),
        total_items=int(paper["total_items"]),
        score_obtained=paper.get("score_obtained"),
        total_score=paper.get("total_score"),
        created_at=paper["created_at"],
        submitted_at=paper.get("submitted_at"),
        graded_at=paper.get("graded_at"),
    )


def _to_exam_paper_detail_response(detail: ExamPaperDetail) -> ExamPaperDetailResponse:
    paper = detail.paper
    items: list[ExamPaperItemResponse] = []
    for item in detail.items:
        items.append(
            ExamPaperItemResponse(
                id=int(item["id"]),
                item_order=int(item["item_order"]),
                question_template_id=int(item["question_template_id"]),
                question_type=str(item["question_type"]),
                difficulty=str(item["difficulty"]),
                stem=str(item["stem"]),
                options=item.get("options"),
                explanation=str(item["explanation"]),
                teaching_unit_id=int(item["teaching_unit_id"]),
                node_links=item.get("node_links", []),
                user_answer=item.get("user_answer"),
                is_correct=item.get("is_correct"),
                score_obtained=item.get("score_obtained"),
                score_max=item.get("score_max"),
                error_cause_label=item.get("error_cause_label"),
            )
        )

    return ExamPaperDetailResponse(
        id=int(paper["id"]),
        subject=str(paper["subject"]),
        user_id=str(paper["user_id"]),
        exam_mode=str(paper["exam_mode"]),
        status=str(paper["status"]),
        total_items=int(paper["total_items"]),
        score_obtained=paper.get("score_obtained"),
        total_score=paper.get("total_score"),
        submitted_at=paper.get("submitted_at"),
        graded_at=paper.get("graded_at"),
        created_at=paper["created_at"],
        items=items,
    )


def _to_question_bank_item_response(item: QuestionBankItem) -> QuestionBankItemResponse:
    return QuestionBankItemResponse(
        question_template_id=item.question_template_id,
        stem=item.stem,
        question_type=item.question_type,
        difficulty=item.difficulty,
        teaching_unit_id=item.teaching_unit_id,
        times_asked=item.times_asked,
        last_asked_at=item.last_asked_at,
        last_exam_paper_id=item.last_exam_paper_id,
    )


@router.post(
    "/generate",
    response_model=ApiResponse[ExamGenerateJobStatusResponse],
    summary="Trigger exam generation",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def api_trigger_exam_generate(
    subject: str = Path(...),
    body: ExamGenerateRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGenerateJobStatusResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    job = await trigger_exam_generate(
        session,
        subject=normalized,
        user_id=user.user_id,
        exam_mode=body.exam_mode,
        num_questions=body.num_questions,
        user_prompt=body.user_prompt,
        theme_tree_node_id=body.theme_tree_node_id,
        teaching_unit_ids=body.teaching_unit_ids,
    )
    return ok_response(_to_exam_generate_job_response(job))


@router.post(
    "/history",
    response_model=ApiResponse[PaginatedData[ExamHistoryItem]],
    summary="Paginated exam history",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_exam_history(
    subject: str = Path(...),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ExamHistoryItem]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    history = await get_exam_history(
        session,
        subject=normalized,
        user_id=user.user_id,
        page=page,
        size=size,
    )
    return ok_response(
        build_paginated_data(
            items=[_to_exam_history_item(item) for item in history.items],
            page=history.page,
            size=history.size,
            total=history.total,
        )
    )


@router.post(
    "/generate-jobs/{job_id:int}",
    response_model=ApiResponse[ExamGenerateJobStatusResponse],
    summary="Exam generate job status",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_generate_job_status(
    subject: str = Path(...),
    job_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGenerateJobStatusResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    job = await get_exam_generate_job_status(
        session,
        subject=normalized,
        job_id=job_id,
        user_id=user.user_id,
    )
    return ok_response(_to_exam_generate_job_response(job))


@router.post(
    "/grade-jobs/{job_id:int}",
    response_model=ApiResponse[ExamGradeJobStatusResponse],
    summary="Exam grade job status",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_grade_job_status(
    subject: str = Path(...),
    job_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGradeJobStatusResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    job = await get_exam_grade_job_status(
        session,
        subject=normalized,
        job_id=job_id,
        user_id=user.user_id,
    )
    return ok_response(_to_exam_grade_job_response(job))


@router.post(
    "/question-bank",
    response_model=ApiResponse[list[QuestionBankItemResponse]],
    summary="Question bank view",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_question_bank(
    subject: str = Path(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[list[QuestionBankItemResponse]]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    items = await get_question_bank(session, subject=normalized, user_id=user.user_id)
    return ok_response([_to_question_bank_item_response(item) for item in items])


@router.post(
    "/{exam_paper_id:int}",
    response_model=ApiResponse[ExamPaperDetailResponse],
    summary="Exam paper detail",
    responses=build_error_responses([400, 404, 500]),
)
async def api_get_exam_detail(
    subject: str = Path(...),
    exam_paper_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDetailResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    detail = await get_exam_paper_detail(
        session,
        subject=normalized,
        user_id=user.user_id,
        exam_paper_id=exam_paper_id,
    )
    return ok_response(_to_exam_paper_detail_response(detail))


@router.post(
    "/{exam_paper_id:int}/delete",
    response_model=ApiResponse[ExamPaperDeleteResponse],
    summary="Delete exam paper",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def api_delete_exam(
    subject: str = Path(...),
    exam_paper_id: int = Path(..., ge=1),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDeleteResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)
    await delete_exam_paper(
        session,
        subject=normalized,
        user_id=user.user_id,
        exam_paper_id=exam_paper_id,
    )
    return ok_response(ExamPaperDeleteResponse(deleted=True, exam_paper_id=exam_paper_id))


@router.post(
    "/{exam_paper_id:int}/submit",
    response_model=ApiResponse[ExamPaperDetailResponse],
    summary="Submit exam answers",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def api_submit_exam(
    subject: str = Path(...),
    exam_paper_id: int = Path(..., ge=1),
    body: ExamSubmitRequest = Body(...),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamPaperDetailResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)

    answers: dict[int | str, str] = {}
    for answer in body.answers:
        if answer.exam_paper_item_id is not None:
            answers[answer.exam_paper_item_id] = answer.answer
        elif answer.item_order is not None:
            answers[answer.item_order] = answer.answer

    await submit_exam_answers(
        session,
        subject=normalized,
        exam_paper_id=exam_paper_id,
        user_id=user.user_id,
        answers=answers,
    )
    detail = await get_exam_paper_detail(
        session,
        subject=normalized,
        user_id=user.user_id,
        exam_paper_id=exam_paper_id,
    )
    return ok_response(_to_exam_paper_detail_response(detail))


@router.post(
    "/{exam_paper_id:int}/grade",
    response_model=ApiResponse[ExamGradeJobStatusResponse],
    summary="Trigger exam grading",
    responses=build_error_responses([400, 404, 409, 500]),
)
async def api_trigger_exam_grade(
    subject: str = Path(...),
    exam_paper_id: int = Path(..., ge=1),
    regrade: bool = Query(False),
    user: CurrentUserContext = Depends(get_current_user_context),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamGradeJobStatusResponse]:
    normalized = normalize_subject_slug(subject)
    get_subject_record(session, normalized)

    await get_exam_paper_detail(
        session,
        subject=normalized,
        user_id=user.user_id,
        exam_paper_id=exam_paper_id,
    )
    job = await trigger_exam_grade(
        session,
        exam_paper_id=exam_paper_id,
        regrade=regrade,
    )
    return ok_response(_to_exam_grade_job_response(job))
