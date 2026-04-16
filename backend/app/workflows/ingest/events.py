"""Canonical ingest domain events."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.utils.time import utcnow


@dataclass(slots=True)
class IngestParseRequestedEvent:
    event_name: ClassVar[str] = "ingest.file.parse.requested"
    subject: str
    file_id: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class IngestFileClassifiedEvent:
    event_name: ClassVar[str] = "ingest.file.classified"
    subject: str
    file_id: int
    file_category: str
    recommended_parser: str
    detected_language: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class IngestFileFastParsedEvent:
    event_name: ClassVar[str] = "ingest.file.fast_parsed"
    subject: str
    file_id: int
    parser_used: str
    markdown_chars: int
    image_count: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class IngestFileParsedEvent:
    event_name: ClassVar[str] = "ingest.file.parsed"
    subject: str
    file_id: int
    parser_used: str
    markdown_chars: int
    image_count: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class IngestFileEnhanceStartedEvent:
    event_name: ClassVar[str] = "ingest.file.enhance.started"
    subject: str
    file_id: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class IngestFileReadyForDigestEvent:
    event_name: ClassVar[str] = "ingest.file.ready_for_digest"
    subject: str
    file_id: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class IngestFileEnhanceFailedEvent:
    event_name: ClassVar[str] = "ingest.file.enhance.failed"
    subject: str
    file_id: int
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class IngestFileParseFailedEvent:
    event_name: ClassVar[str] = "ingest.file.parse.failed"
    subject: str
    file_id: int
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)


__all__ = [
    "IngestFileClassifiedEvent",
    "IngestFileEnhanceFailedEvent",
    "IngestFileEnhanceStartedEvent",
    "IngestFileFastParsedEvent",
    "IngestFileParseFailedEvent",
    "IngestFileParsedEvent",
    "IngestFileReadyForDigestEvent",
    "IngestParseRequestedEvent",
]
