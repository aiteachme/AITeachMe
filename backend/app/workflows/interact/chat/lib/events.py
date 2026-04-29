"""Domain events emitted by the interact chat lane."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.utils.time import utcnow


@dataclass(slots=True)
class InteractRequestedEvent:
    """A chat interaction has been requested."""

    event_name: ClassVar[str] = "interact.requested"

    course_id: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class InteractCompletedEvent:
    """A chat interaction has completed."""

    event_name: ClassVar[str] = "interact.completed"

    course_id: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class InteractFailedEvent:
    """A chat interaction has failed."""

    event_name: ClassVar[str] = "interact.failed"

    course_id: str
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)


__all__ = [
    "InteractCompletedEvent",
    "InteractFailedEvent",
    "InteractRequestedEvent",
]
