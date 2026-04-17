"""Shared digest domain events for digest lanes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.utils.time import utcnow


@dataclass(slots=True)
class DigestBuildRequestedEvent:
    event_name: ClassVar[str] = "digest.build.requested"
    subject: str
    job_id: int
    file_ids: list[int]
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DigestGraphCompletedEvent:
    event_name: ClassVar[str] = "digest.graph.completed"
    subject: str
    job_id: int
    file_ids: list[int]
    chunk_count: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DigestGraphFailedEvent:
    event_name: ClassVar[str] = "digest.graph.failed"
    subject: str
    job_id: int
    file_ids: list[int]
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DocGenRequestedEvent:
    event_name: ClassVar[str] = "digest.docgen.requested"
    subject: str
    requested_at: datetime
    file_ids: list[int]
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DocGenCompletedEvent:
    event_name: ClassVar[str] = "digest.docgen.completed"
    subject: str
    requested_at: datetime
    staged_chapter_count: int
    draft_available: bool
    published_doc_count: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DocGenFailedEvent:
    event_name: ClassVar[str] = "digest.docgen.failed"
    subject: str
    requested_at: datetime
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)


__all__ = [
    "DigestBuildRequestedEvent",
    "DigestGraphCompletedEvent",
    "DigestGraphFailedEvent",
    "DocGenCompletedEvent",
    "DocGenFailedEvent",
    "DocGenRequestedEvent",
]
