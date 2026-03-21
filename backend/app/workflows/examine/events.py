"""Domain events for the examine workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.utils.time import utcnow


@dataclass(slots=True)
class ExamineRequestedEvent:
    """An exam workflow has been requested."""

    event_name: ClassVar[str] = "examine.requested"

    subject: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class ExamineCompletedEvent:
    """An exam workflow has completed."""

    event_name: ClassVar[str] = "examine.completed"

    subject: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class ExamineFailedEvent:
    """An exam workflow has failed."""

    event_name: ClassVar[str] = "examine.failed"

    subject: str
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)
