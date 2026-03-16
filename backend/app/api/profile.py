"""学习画像接口。"""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.common import ApiResponse, PaginatedData, ok_response
from app.schemas.profile import MistakeItem, ProfileItem, ProfileListRequest, ProfileMistakesRequest, ProfileReportRequest, ReportData
from app.services.profile_service import get_report, list_mistakes, list_profiles
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/profile", tags=["profile"])


@router.post(
    "/list",
    response_model=ApiResponse[PaginatedData[ProfileItem]],
    summary="掌握度列表",
    responses=build_error_responses([400, 404, 500]),
)
async def list_profile_points(
    subject: str = Path(...),
    body: ProfileListRequest = Body(default=ProfileListRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[ProfileItem]]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(
        list_profiles(
            session,
            subject=normalized_subject,
            page=body.page,
            size=body.size,
        )
    )


@router.post(
    "/report",
    response_model=ApiResponse[ReportData],
    summary="学习报告",
    responses=build_error_responses([400, 404, 500, 502, 503]),
)
async def get_profile_report(
    subject: str = Path(...),
    _: ProfileReportRequest = Body(default=ProfileReportRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[ReportData]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(await get_report(session, subject=normalized_subject))


@router.post(
    "/mistakes",
    response_model=ApiResponse[PaginatedData[MistakeItem]],
    summary="错题本",
    responses=build_error_responses([400, 404, 500]),
)
async def list_profile_mistakes(
    subject: str = Path(...),
    body: ProfileMistakesRequest = Body(default=ProfileMistakesRequest()),
    session: Session = Depends(get_db),
) -> ApiResponse[PaginatedData[MistakeItem]]:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    return ok_response(
        list_mistakes(
            session,
            subject=normalized_subject,
            page=body.page,
            size=body.size,
        )
    )
