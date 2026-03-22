"""Domain events for the profile workflow."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.utils.time import utcnow


@dataclass(slots=True)
class ProfileRequestedEvent:
    """A profile workflow has been requested."""

    event_name: ClassVar[str] = "profile.requested"

    subject: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class ProfileCompletedEvent:
    """A profile workflow has completed."""

    event_name: ClassVar[str] = "profile.completed"

    subject: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class ProfileFailedEvent:
    """A profile workflow has failed."""

    event_name: ClassVar[str] = "profile.failed"

    subject: str
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)
