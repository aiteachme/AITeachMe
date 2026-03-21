"""Ingest domain events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.utils.time import utcnow


@dataclass(slots=True)
class IngestParseRequestedEvent:
    """A raw file parse workflow has been requested."""

    event_name: ClassVar[str] = "ingest.file.parse.requested"

    subject: str
    file_id: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class IngestFileClassifiedEvent:
    """A raw file has completed lightweight classification."""

    event_name: ClassVar[str] = "ingest.file.classified"

    subject: str
    file_id: int
    file_category: str
    recommended_parser: str
    detected_language: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class IngestFileParsedEvent:
    """A raw file has been converted into normalized markdown."""

    event_name: ClassVar[str] = "ingest.file.parsed"

    subject: str
    file_id: int
    parser_used: str
    markdown_chars: int
    image_count: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class IngestFileReadyForDigestEvent:
    """A raw file is ready for downstream digest processing."""

    event_name: ClassVar[str] = "ingest.file.ready_for_digest"

    subject: str
    file_id: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class IngestFileParseFailedEvent:
    """A raw file parse workflow has failed."""

    event_name: ClassVar[str] = "ingest.file.parse.failed"

    subject: str
    file_id: int
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)
