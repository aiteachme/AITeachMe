"""User repository helpers."""

from __future__ import annotations

from sqlmodel import Session, select

from app.models import User
from app.utils.time import utcnow


def get_user_by_username(session: Session, username: str) -> User | None:
    return session.exec(select(User).where(User.username == username)).first()


def get_or_create_user_by_username(
    session: Session,
    *,
    username: str,
    email: str | None = None,
) -> User:
    user = get_user_by_username(session, username)
    if user is not None:
        return user

    user = User(username=username, email=email, profile_json="{}")
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def touch_user_last_seen(
    session: Session,
    *,
    user: User,
    last_used_ip: str | None = None,
    email: str | None = None,
) -> User:
    if last_used_ip is not None:
        user.last_used_ip = last_used_ip
    if email is not None:
        user.email = email
    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)
    return user
