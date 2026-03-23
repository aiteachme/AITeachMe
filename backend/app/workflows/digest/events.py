"""Digest domain events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.utils.time import utcnow


@dataclass(slots=True)
class DigestBuildRequestedEvent:
    """Digest graph build requested."""

    event_name: ClassVar[str] = "digest.build.requested"

    subject: str
    job_id: int
    file_ids: list[int]
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DigestGraphCompletedEvent:
    """Digest graph build completed."""

    event_name: ClassVar[str] = "digest.graph.completed"

    subject: str
    job_id: int
    file_ids: list[int]
    chunk_count: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DigestGraphFailedEvent:
    """Digest graph build failed."""

    event_name: ClassVar[str] = "digest.graph.failed"

    subject: str
    job_id: int
    file_ids: list[int]
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class CurriculumDeriveCompletedEvent:
    """Curriculum derive completed."""

    event_name: ClassVar[str] = "digest.curriculum.completed"

    subject: str
    graph_job_id: int
    curriculum_job_id: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class CurriculumDeriveFailedEvent:
    """Curriculum derive failed."""

    event_name: ClassVar[str] = "digest.curriculum.failed"

    subject: str
    graph_job_id: int
    curriculum_job_id: int
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DocGenRequestedEvent:
    """Knowledge docs build requested."""

    event_name: ClassVar[str] = "digest.docgen.requested"

    subject: str
    requested_at: datetime
    file_ids: list[int]
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DocGenCompletedEvent:
    """Knowledge docs build completed."""

    event_name: ClassVar[str] = "digest.docgen.completed"

    subject: str
    requested_at: datetime
    doc_count: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class DocGenFailedEvent:
    """Knowledge docs build failed."""

    event_name: ClassVar[str] = "digest.docgen.failed"

    subject: str
    requested_at: datetime
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)
