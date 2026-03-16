"""Subject-scoped profile routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends, Path
from sqlmodel import Session

from app.api.deps import get_db, normalize_subject_slug
from app.api.openapi import build_error_responses
from app.schemas.profile import (
    ProfileListRequest,
    ProfileListResponse,
    ProfileMistakesRequest,
    ProfileMistakesResponse,
    ProfileReportRequest,
    ReportResponse,
)
from app.services.presenters import to_mistake_list_response, to_profile_response, to_report_response
from app.services.profile_service import get_mistakes, get_profiles, get_report
from app.services.subject_service import get_subject_record

router = APIRouter(prefix="/api/v1/subjects/{subject}/profile", tags=["profile"])


@router.post(
    "/list",
    response_model=ProfileListResponse,
    summary="List profile mastery points",
    description="Return paginated mastery records for one subject.",
    response_description="Paginated mastery records.",
    responses=build_error_responses([400, 404, 500]),
)
async def list_profile_points(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: ProfileListRequest = Body(default=ProfileListRequest()),
    session: Session = Depends(get_db),
) -> ProfileListResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    items, total = await get_profiles(session, normalized_subject, limit=body.limit, offset=body.offset)
    return to_profile_response(items, total)


@router.post(
    "/report",
    response_model=ReportResponse,
    summary="Get profile report",
    description="Return overall mastery, weak points, and study suggestions for one subject.",
    response_description="Learning profile report.",
    responses=build_error_responses([400, 404, 500, 502, 503]),
)
async def get_profile_report(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    _: ProfileReportRequest = Body(default=ProfileReportRequest()),
    session: Session = Depends(get_db),
) -> ReportResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    report = await get_report(session, normalized_subject)
    return to_report_response(report)


@router.post(
    "/mistakes",
    response_model=ProfileMistakesResponse,
    summary="List profile mistakes",
    description="Return paginated mistake-book items for one subject.",
    response_description="Paginated mistakes.",
    responses=build_error_responses([400, 404, 500]),
)
async def list_profile_mistakes(
    subject: str = Path(..., description="Top-level subject slug.", examples=["math"]),
    body: ProfileMistakesRequest = Body(default=ProfileMistakesRequest()),
    session: Session = Depends(get_db),
) -> ProfileMistakesResponse:
    normalized_subject = normalize_subject_slug(subject)
    get_subject_record(session, normalized_subject)
    items, total = await get_mistakes(session, normalized_subject, limit=body.limit, offset=body.offset)
    return to_mistake_list_response(items, total)
