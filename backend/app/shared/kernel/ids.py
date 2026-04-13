"""Shared ID validation helpers."""

from __future__ import annotations


def require_id(value: int | None, field_name: str) -> int:
    """Ensure a persisted integer primary key exists."""

    if value is None:
        raise ValueError(f"{field_name} must not be empty after persistence.")
    return value


def require_uid(value: str | None, field_name: str) -> str:
    """Ensure a persisted public UID exists."""

    if value is None or not value.strip():
        raise ValueError(f"{field_name} must not be empty after persistence.")
    return value


__all__ = ["require_id", "require_uid"]
