"""Shared presenter-layer helpers.

Pure formatting / validation helpers with no business logic.
Canonical location: ``app.utils.presenters``.
"""

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


def mastery_to_text(mastery: float | None) -> str:
    """Convert mastery ratio to display text."""

    if mastery is None:
        return "暂无数据"
    return f"{mastery:.0%}"
