"""学习画像服务层。"""

from __future__ import annotations

from sqlmodel import Session

from app.agents.profile.reporter import generate_report_suggestions
from app.repositories.exams_repo import list_mistakes_by_subject
from app.repositories.profile_repo import get_weak_points, list_profiles_by_subject
from app.schemas.common import PaginatedData, build_paginated_data
from app.schemas.profile import MistakeItem, ProfileItem, ReportData
from app.services.presenters import mastery_to_text


def list_profiles(
    session: Session,
    *,
    subject: str,
    page: int,
    size: int,
) -> PaginatedData[ProfileItem]:
    """分页读取知识点掌握度。"""

    items, total = list_profiles_by_subject(
        session,
        subject,
        limit=size,
        offset=(page - 1) * size,
    )
    return build_paginated_data(
        items=[
            ProfileItem(
                knowledge_point=item.knowledge_point,
                mastery=item.mastery,
                attempts=item.attempts,
                correct=item.correct,
            )
            for item in items
        ],
        page=page,
        size=size,
        total=total,
    )


async def get_report(session: Session, *, subject: str) -> ReportData:
    """生成学习报告。"""

    all_profiles, _ = list_profiles_by_subject(session, subject, limit=10000, offset=0)
    tested_profiles = [item for item in all_profiles if item.mastery is not None and item.attempts > 0]
    overall_mastery = None
    if tested_profiles:
        total_attempts = sum(item.attempts for item in tested_profiles)
        if total_attempts > 0:
            overall_mastery = sum(item.correct for item in tested_profiles) / total_attempts

    weak_profiles = get_weak_points(session, subject, limit=5)
    suggestions = await generate_report_suggestions(
        subject=subject,
        overall_mastery=overall_mastery,
        weak_points=[
            {
                "knowledge_point": item.knowledge_point,
                "mastery_text": mastery_to_text(item.mastery),
            }
            for item in weak_profiles
        ],
    )
    return ReportData(
        overall_mastery=overall_mastery,
        weak_points_top5=[
            ProfileItem(
                knowledge_point=item.knowledge_point,
                mastery=item.mastery,
                attempts=item.attempts,
                correct=item.correct,
            )
            for item in weak_profiles
        ],
        suggestions=suggestions,
    )


def list_mistakes(
    session: Session,
    *,
    subject: str,
    page: int,
    size: int,
) -> PaginatedData[MistakeItem]:
    """分页读取错题本。"""

    items, total = list_mistakes_by_subject(
        session,
        subject,
        limit=size,
        offset=(page - 1) * size,
    )
    return build_paginated_data(
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
        page=page,
        size=size,
        total=total,
    )
