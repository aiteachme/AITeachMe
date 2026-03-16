"""测验接口。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.schemas.exam import (
    ExamData,
    ExamDeleteData,
    ExamDeleteRequest,
    ExamHistoryItem,
    ExamListRequest,
    ExamMakeRequest,
    ExamSubmitRequest,
    SubmitData,
)
from app.services.exam_service import create_exam, delete_exam, list_exams, submit_exam
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/exam", tags=["exam"])


@router.post(
    "/make",
    response_model=ApiResponse[ExamData],
    summary="生成试卷",
    responses=build_error_responses([400, 404, 500, 502, 503]),
)
async def make_exam(
    subject: str = Path(...),
    body: ExamMakeRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(
        await create_exam(
            session,
            subject=normalized_subject,
            num_questions=body.num,
            knowledge_points=body.points,
        )
    )


@router.post(
    "/submit",
    response_model=ApiResponse[SubmitData],
    summary="提交试卷",
    responses=build_error_responses([400, 404, 500, 502, 503]),
)
async def submit_exam_answers(
    subject: str = Path(...),
    body: ExamSubmitRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[SubmitData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(
        await submit_exam(
            session,
            subject=normalized_subject,
            exam_id=body.exam_id,
            answers={item.question_key: item.answer for item in body.answers},
        )
    )


@router.post(
    "/list",
    response_model=ApiResponse[PaginatedData[ExamHistoryItem]],
    summary="试卷历史",
    responses=build_error_responses([400, 404, 500]),
)
async def list_exams_api(
    subject: str = Path(...),
    body: ExamListRequest = Body(default=ExamListRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ExamHistoryItem]]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(
        list_exams(
            session,
            subject=normalized_subject,
            page=body.page,
            size=body.size,
        )
    )


@router.post(
    "/delete",
    response_model=ApiResponse[ExamDeleteData],
    summary="删除试卷",
    responses=build_error_responses([400, 404, 500]),
)
async def delete_exam_api(
    subject: str = Path(...),
    body: ExamDeleteRequest = Body(...),
    session: Session = Depends(get_db),
) -> ApiResponse[ExamDeleteData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(delete_exam(session, subject=normalized_subject, exam_id=body.exam_id))
