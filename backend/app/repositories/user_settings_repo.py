"""Repository helpers for per-user runtime settings."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.models import User
from app.utils.time import utcnow


def get_user_runtime_settings(session: Session, user_id: str) -> User | None:
    """Return the user row that owns runtime settings."""

    return session.get(User, user_id)


def get_user_runtime_settings_payload(session: Session, user_id: str) -> dict[str, Any]:
    """Return a safe dict payload for one user's non-secret settings."""

    row = get_user_runtime_settings(session, user_id)
    if row is None or not isinstance(row.runtime_settings_json, dict):
        return {}
    return dict(row.runtime_settings_json)


def upsert_user_runtime_settings_payload(
    session: Session,
    *,
    user_id: str,
    payload: dict[str, Any],
) -> User:
    """Create or update one user's non-secret settings payload."""

    row = get_user_runtime_settings(session, user_id)
    if row is None:
        raise RuntimeError(f"Cannot update runtime settings for missing user `{user_id}`.")
    row.runtime_settings_json = dict(payload)
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def clear_user_runtime_settings(session: Session, *, user_id: str) -> User:
    """Clear all user overrides on the owning user row."""

    return upsert_user_runtime_settings_payload(session, user_id=user_id, payload={})
