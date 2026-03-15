"""
画像端点

GET /api/v1/profile/{subject} — 分页掌握度列表
GET /api/v1/profile/{subject}/report — 学习进度报告
GET /api/v1/mistakes/{subject} — 分页错题列表

需求：11.4, 11.5, 11.6
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.api.deps import get_db, validate_subject, PaginationParams
from app.schemas.profile import (
    ProfileItem,
    ProfileResponse,
    ReportResponse,
    MistakeItem,
    MistakeListResponse,
)
from app.services.profile_service import get_profiles, get_report, get_mistakes

router = APIRouter(prefix="/api/v1", tags=["profile"])


@router.get("/profile/{subject}", response_model=ProfileResponse)
async def list_profiles(
    subject: str = Depends(validate_subject),
    pagination: PaginationParams = Depends(),
    session: Session = Depends(get_db),
) -> ProfileResponse:
    """分页掌握度列表。"""
    items, total = await get_profiles(
        session, subject, limit=pagination.limit, offset=pagination.offset
    )
    return ProfileResponse(
        items=[
            ProfileItem(
                knowledge_point=p.knowledge_point,
                mastery=p.mastery,
                attempts=p.attempts,
                correct=p.correct,
            )
            for p in items
        ],
        total=total,
    )


@router.get("/profile/{subject}/report", response_model=ReportResponse)
async def get_learning_report(
    subject: str = Depends(validate_subject),
    session: Session = Depends(get_db),
) -> ReportResponse:
    """学习进度报告。"""
    report = await get_report(session, subject)
    return ReportResponse(
        overall_mastery=report["overall_mastery"],
        weak_points_top5=[
            ProfileItem(
                knowledge_point=p.knowledge_point,
                mastery=p.mastery,
                attempts=p.attempts,
                correct=p.correct,
            )
            for p in report["weak_points_top5"]
        ],
        suggestions=report["suggestions"],
    )


@router.get("/mistakes/{subject}", response_model=MistakeListResponse)
async def list_mistakes(
    subject: str = Depends(validate_subject),
    pagination: PaginationParams = Depends(),
    session: Session = Depends(get_db),
) -> MistakeListResponse:
    """分页错题列表。"""
    items, total = await get_mistakes(
        session, subject, limit=pagination.limit, offset=pagination.offset
    )
    return MistakeListResponse(
        items=[
            MistakeItem(
                id=item["id"],
                question_stem=item["question_stem"],
                question_type=item["question_type"],
                user_answer=item["user_answer"],
                correct_answer=item["correct_answer"],
                analysis=item["analysis"],
                knowledge_point=item["knowledge_point"],
                created_at=item["created_at"],
            )
            for item in items
        ],
        total=total,
    )
