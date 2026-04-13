"""Shared time helpers."""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Return the current UTC time as an aware datetime."""

    return datetime.now(timezone.utc)


__all__ = ["utcnow"]
