"""
画像查询编排 �?协调画像列表、报告生成、错题列�?
"""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.agents.profile.reporter import generate_report
from app.repositories import profile_repo, exam_repo
from app.repositories.models import UserProfile

logger = structlog.get_logger()


async def get_profiles(
    session: Session,
    subject: str,
    *,
    user_id: str = "local",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[UserProfile], int]:
    """分页查询学科下所有知识点掌握度�?""
    return profile_repo.list_profiles_by_subject(
        session, subject, user_id=user_id, limit=limit, offset=offset
    )


async def get_report(
    session: Session,
    subject: str,
    *,
    user_id: str = "local",
) -> dict:
    """
    生成学习进度报告�?

    Returns:
        {
            "overall_mastery": float | None,
            "weak_points_top5": list[UserProfile],
            "suggestions": list[str],
        }
    """
    return await generate_report(session, subject, user_id=user_id)


async def get_mistakes(
    session: Session,
    subject: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """分页查询学科下的错题列表�?""
    return exam_repo.list_mistakes_by_subject(
        session, subject, limit=limit, offset=offset
    )
