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
        id=paper.id or 0,
        subject=paper.subject,
        user_id=paper.user_id,
        exam_mode=paper.exam_mode,
        status=paper.status,
        total_items=paper.total_items,
        score_obtained=paper.score_obtained,
        total_score=paper.total_score,
        created_at=paper.created_at,
        submitted_at=paper.submitted_at,
        graded_at=paper.graded_at,
    )


def _to_exam_paper_detail_response(detail: ExamPaperDetail) -> ExamPaperDetailResponse:
    paper = detail.paper
    items: list[ExamPaperItemResponse] = []
    for item in detail.items:
        options = _parse_json_list(item.snapshot_options)
        attempts = detail.attempts_by_item_id.get(item.id or -1)
        items.append(
            ExamPaperItemResponse(
                id=item.id or 0,
                item_order=item.item_order,
                question_template_id=item.question_template_id,
                question_type=item.snapshot_question_type,
                difficulty=item.snapshot_difficulty,
                stem=item.snapshot_stem,
                options=[str(option) for option in options] if options else None,
                explanation=item.snapshot_explanation,
                teaching_unit_id=item.snapshot_teaching_unit_id,
                node_links=_parse_json_list(item.snapshot_node_links_json),
                user_answer=(attempts.user_answer if attempts is not None else None),
                is_correct=(attempts.is_correct if attempts is not None else None),
                score_obtained=(attempts.score_obtained if attempts is not None else None),
                score_max=(attempts.score_max if attempts is not None else None),
                error_cause_label=(attempts.error_cause_label if attempts is not None else None),
            )
        )

    return ExamPaperDetailResponse(
        id=paper.id or 0,
        subject=paper.subject,
        user_id=paper.user_id,
        exam_mode=paper.exam_mode,
        status=paper.status,
        total_items=paper.total_items,
        score_obtained=paper.score_obtained,
        total_score=paper.total_score,
        submitted_at=paper.submitted_at,
        graded_at=paper.graded_at,
        created_at=paper.created_at,
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


@router.get(
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


@router.get(
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


@router.get(
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


@router.get(
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


@router.get(
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


@router.delete(
    "/{exam_paper_id:int}",
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
