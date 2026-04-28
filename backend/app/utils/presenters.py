"""Shared presenter-layer helpers.

Pure formatting / validation helpers with no business logic.
Canonical location: ``app.utils.presenters``.
"""

from __future__ import annotations

from typing import TypeVar

_ID = TypeVar("_ID", int, str)


def require_id(value: _ID | None, field_name: str) -> _ID:
    """Ensure a persisted primary key exists."""

    if value is None or (isinstance(value, str) and not value.strip()):
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
