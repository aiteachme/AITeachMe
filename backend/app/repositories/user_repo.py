"""User repository helpers."""

from __future__ import annotations

import re
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.models import User
from app.utils.time import utcnow

_USERNAME_SANITIZE_RE = re.compile(r"[^a-zA-Z0-9_]+")


def _new_user_id() -> str:
    return f"usr_{uuid4().hex[:20]}"


def _normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    normalized = email.strip().lower()
    return normalized or None


def _build_guest_username(device_key: str) -> str:
    suffix = _USERNAME_SANITIZE_RE.sub("", device_key.lower())[-12:]
    suffix = suffix or uuid4().hex[:8]
    return f"guest_{suffix}"


def get_user_by_id(session: Session, user_id: str) -> User | None:
    return session.get(User, user_id)


def get_user_by_username(session: Session, username: str) -> User | None:
    return session.exec(select(User).where(User.username == username)).first()


def get_user_by_email(session: Session, email: str) -> User | None:
    normalized = _normalize_email(email)
    if not normalized:
        return None
    return session.exec(select(User).where(User.email == normalized)).first()


def get_user_by_device_key(session: Session, device_key: str) -> User | None:
    normalized = device_key.strip()
    if not normalized:
        return None
    return session.exec(select(User).where(User.device_key == normalized)).first()


def create_user(
    session: Session,
    *,
    username: str,
    email: str | None = None,
    device_key: str | None = None,
    password_hash: str | None = None,
    is_registered: bool = False,
) -> User:
    normalized_email = _normalize_email(email)
    normalized_device_key = (device_key or "").strip() or None
    user = User(
        id=_new_user_id(),
        username=username.strip(),
        email=normalized_email,
        device_key=normalized_device_key,
        password_hash=password_hash,
        is_registered=is_registered,
        profile_json="{}",
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def get_or_create_user_by_username(
    session: Session,
    *,
    username: str,
    email: str | None = None,
) -> User:
    normalized_username = username.strip()
    user = get_user_by_username(session, normalized_username)
    if user is not None:
        return user
    return create_user(
        session,
        username=normalized_username,
        email=email,
        is_registered=bool(email),
    )


def get_or_create_user_by_device_key(session: Session, *, device_key: str) -> User:
    normalized_device_key = device_key.strip()
    user = get_user_by_device_key(session, normalized_device_key)
    if user is not None:
        return user

    base_username = _build_guest_username(normalized_device_key)
    username = base_username
    suffix = 1
    while get_user_by_username(session, username) is not None:
        suffix += 1
        username = f"{base_username}_{suffix}"

    return create_user(
        session,
        username=username,
        device_key=normalized_device_key,
        is_registered=False,
    )


def attach_device_key(
    session: Session,
    *,
    user: User,
    device_key: str,
) -> User:
    normalized_device_key = device_key.strip()
    if not normalized_device_key:
        return user

    user_id = user.id
    latest_user: User | None = user
    last_error: IntegrityError | None = None

    for _ in range(3):
        latest_user = get_user_by_id(session, user_id)
        if latest_user is None:
            raise RuntimeError(f"User `{user_id}` disappeared before device_key attach.")

        if latest_user.device_key == normalized_device_key:
            return latest_user

        owner = get_user_by_device_key(session, normalized_device_key)
        if owner is not None and owner.id != user_id:
            owner.device_key = None
            owner.updated_at = utcnow()
            session.add(owner)
            # Flush first to clear the old binding before assigning the same
            # device_key to the new user, otherwise SQLite's per-row UNIQUE
            # check inside executemany will fail.
            session.flush()

        latest_user.device_key = normalized_device_key
        latest_user.updated_at = utcnow()
        session.add(latest_user)
        try:
            session.commit()
            session.refresh(latest_user)
            return latest_user
        except IntegrityError as exc:
            session.rollback()
            last_error = exc

    if latest_user is not None and not latest_user.is_registered:
        owner = get_user_by_device_key(session, normalized_device_key)
        if owner is not None and not owner.is_registered:
            return owner

    if last_error is not None:
        raise last_error
    return user


def touch_user_last_seen(
    session: Session,
    *,
    user: User,
    last_seen_ip: str | None = None,
    email: str | None = None,
) -> User:
    if last_seen_ip is not None:
        user.last_seen_ip = last_seen_ip

    normalized_email = _normalize_email(email)
    if normalized_email is not None:
        user.email = normalized_email

    user.updated_at = utcnow()
    session.add(user)
    session.commit()
    session.refresh(user)
    return user

