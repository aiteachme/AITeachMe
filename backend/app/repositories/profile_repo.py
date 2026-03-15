"""
UserProfile CRUD — 掌握度画像数据访问
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Session, select, func

from app.repositories.models import UserProfile


def upsert_profile(
    session: Session,
    *,
    user_id: str,
    subject: str,
    knowledge_point: str,
    attempts: int,
    correct: int,
) -> UserProfile:
    """
    按 (user_id, subject, knowledge_point) 进行 upsert。
    mastery = correct / attempts（attempts > 0），否则 None。
    """
    stmt = select(UserProfile).where(
        UserProfile.user_id == user_id,
        UserProfile.subject == subject,
        UserProfile.knowledge_point == knowledge_point,
    )
    profile = session.exec(stmt).first()

    mastery = correct / attempts if attempts > 0 else None

    if profile is None:
        profile = UserProfile(
            user_id=user_id,
            subject=subject,
            knowledge_point=knowledge_point,
            mastery=mastery,
            attempts=attempts,
            correct=correct,
            updated_at=datetime.utcnow(),
        )
    else:
        profile.attempts = attempts
        profile.correct = correct
        profile.mastery = mastery
        profile.updated_at = datetime.utcnow()

    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def list_profiles_by_subject(
    session: Session,
    subject: str,
    *,
    user_id: str = "local",
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[UserProfile], int]:
    """按学科分页查询全部 UserProfile，返回 (items, total)。"""
    count_stmt = (
        select(func.count())
        .select_from(UserProfile)
        .where(UserProfile.subject == subject, UserProfile.user_id == user_id)
    )
    total = session.exec(count_stmt).one()

    stmt = (
        select(UserProfile)
        .where(UserProfile.subject == subject, UserProfile.user_id == user_id)
        .order_by(UserProfile.updated_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    items = list(session.exec(stmt).all())
    return items, total


def get_weak_points(
    session: Session,
    subject: str,
    *,
    user_id: str = "local",
    threshold: float = 0.6,
) -> list[UserProfile]:
    """获取薄弱点（mastery < threshold），按 mastery 升序排列。"""
    stmt = (
        select(UserProfile)
        .where(
            UserProfile.subject == subject,
            UserProfile.user_id == user_id,
            UserProfile.mastery.is_not(None),  # type: ignore[union-attr]
            UserProfile.mastery < threshold,  # type: ignore[operator]
        )
        .order_by(UserProfile.mastery.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())
