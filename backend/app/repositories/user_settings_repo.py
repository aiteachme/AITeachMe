"""Repository helpers for per-user runtime settings."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.models import UserRuntimeSettings


def get_user_runtime_settings(session: Session, user_id: str) -> UserRuntimeSettings | None:
    """Return the settings row for one user."""

    return session.get(UserRuntimeSettings, user_id)


def get_user_runtime_settings_payload(session: Session, user_id: str) -> dict[str, Any]:
    """Return a safe dict payload for one user's non-secret settings."""

    row = get_user_runtime_settings(session, user_id)
    if row is None or not isinstance(row.settings_json, dict):
        return {}
    return dict(row.settings_json)


def upsert_user_runtime_settings_payload(
    session: Session,
    *,
    user_id: str,
    payload: dict[str, Any],
) -> UserRuntimeSettings:
    """Create or update one user's non-secret settings payload."""

    row = get_user_runtime_settings(session, user_id)
    if row is None:
        row = UserRuntimeSettings(user_id=user_id)
    row.settings_json = payload
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def clear_user_runtime_settings(session: Session, *, user_id: str) -> UserRuntimeSettings:
    """Clear all user overrides while keeping the row for auditability."""

    return upsert_user_runtime_settings_payload(session, user_id=user_id, payload={})
