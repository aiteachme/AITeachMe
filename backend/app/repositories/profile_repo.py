"""学习画像数据访问层。"""

from __future__ import annotations

from sqlmodel import Session, func, select

from app.models import UserProfile
from app.utils.time import utcnow


def upsert_profile(
    session: Session,
    *,
    user_id: str,
    subject: str,
    knowledge_point: str,
    attempts: int,
    correct: int,
) -> UserProfile:
    """更新或创建画像记录。"""

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
            updated_at=utcnow(),
        )
    else:
        profile.mastery = mastery
        profile.attempts = attempts
        profile.correct = correct
        profile.updated_at = utcnow()

    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


def list_profiles_by_subject(
    session: Session,
    subject: str,
    *,
    user_id: str = "local",
    limit: int,
    offset: int,
) -> tuple[list[UserProfile], int]:
    """分页读取学科画像。"""

    total = session.exec(
        select(func.count())
        .select_from(UserProfile)
        .where(UserProfile.subject == subject, UserProfile.user_id == user_id)
    ).one()
    stmt = (
        select(UserProfile)
        .where(UserProfile.subject == subject, UserProfile.user_id == user_id)
        .order_by(UserProfile.updated_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def get_profile_by_key(
    session: Session,
    *,
    user_id: str,
    subject: str,
    knowledge_point: str,
) -> UserProfile | None:
    """按唯一键读取画像。"""

    stmt = select(UserProfile).where(
        UserProfile.user_id == user_id,
        UserProfile.subject == subject,
        UserProfile.knowledge_point == knowledge_point,
    )
    return session.exec(stmt).first()


def get_weak_points(
    session: Session,
    subject: str,
    *,
    user_id: str = "local",
    threshold: float = 0.6,
    limit: int | None = None,
) -> list[UserProfile]:
    """查询薄弱知识点。"""

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
    if limit is not None:
        stmt = stmt.limit(limit)
    return list(session.exec(stmt).all())
