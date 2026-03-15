"""Profile mastery, report, and mistake-book routes."""

from __future__ import annotations

from fastapi import APIRouter, Body, Depends
from sqlmodel import Session

from app.api.docs import build_error_responses
from app.api.deps import get_db, validate_subject, PaginationParams
from app.schemas.profile import (
    MistakeListResponse,
    ProfileResponse,
    ReportResponse,
)
from app.services.profile_service import get_profiles, get_report, get_mistakes
from app.services.presenters import (
    to_mistake_list_response,
    to_profile_response,
    to_report_response,
)

router = APIRouter(prefix="/api/v1", tags=["profile"])


@router.post(
    "/profile/{subject}",
    response_model=ProfileResponse,
    summary="获取学习画像",
    description="分页返回指定学科下的知识点掌握度记录。",
    response_description="掌握度分页列表。",
    responses=build_error_responses([400, 500]),
)
async def list_profiles(
    body: PaginationParams = Body(..., description="分页参数。"),
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> ProfileResponse:
    """Return paginated mastery records for one subject."""
    items, total = await get_profiles(
        session, subject, limit=body.limit, offset=body.offset
    )
    return to_profile_response(items, total)


@router.post(
    "/profile/{subject}/report",
    response_model=ReportResponse,
    summary="获取学习报告",
    description="汇总总体掌握度、薄弱点 Top 5 与个性化复习建议。",
    response_description="学习报告。",
    responses=build_error_responses([400, 500, 502, 503]),
)
async def get_learning_report(
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> ReportResponse:
    """Return an aggregated learning report for one subject."""
    report = await get_report(session, subject)
    return to_report_response(report)


@router.post(
    "/mistakes/{subject}",
    response_model=MistakeListResponse,
    summary="获取错题本",
    description="分页返回指定学科下的错题列表及 AI 错因分析。",
    response_description="错题分页列表。",
    responses=build_error_responses([400, 500]),
)
async def list_mistakes(
    body: PaginationParams = Body(..., description="分页参数。"),
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> MistakeListResponse:
    """Return paginated mistake-book entries for one subject."""
    items, total = await get_mistakes(
        session, subject, limit=body.limit, offset=body.offset
    )
    return to_mistake_list_response(items, total)
