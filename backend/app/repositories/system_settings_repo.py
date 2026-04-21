"""Repository helpers for global runtime settings overrides."""

from __future__ import annotations

from typing import Any

from sqlmodel import Session

from app.models import SystemRuntimeSettings

_SYSTEM_RUNTIME_SETTINGS_ID = "runtime"


def get_system_runtime_settings(session: Session) -> SystemRuntimeSettings | None:
    return session.get(SystemRuntimeSettings, _SYSTEM_RUNTIME_SETTINGS_ID)


def get_system_runtime_settings_payload(session: Session) -> dict[str, Any]:
    row = get_system_runtime_settings(session)
    if row is None or not isinstance(row.settings_json, dict):
        return {}
    return dict(row.settings_json)


def upsert_system_runtime_settings_payload(
    session: Session,
    *,
    payload: dict[str, Any],
) -> SystemRuntimeSettings:
    row = get_system_runtime_settings(session)
    if row is None:
        row = SystemRuntimeSettings(id=_SYSTEM_RUNTIME_SETTINGS_ID)
    row.settings_json = payload
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def clear_system_runtime_settings(session: Session) -> SystemRuntimeSettings:
    return upsert_system_runtime_settings_payload(session, payload={})
