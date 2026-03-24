"""Workflow events for unified digest builds."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import ClassVar

from app.utils.time import utcnow


@dataclass(slots=True)
class UnifiedBuildStartedEvent:
    """Unified digest build started."""

    event_name: ClassVar[str] = "digest.unified.started"

    subject: str
    file_count: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class UnifiedBuildCompletedEvent:
    """Unified digest build completed."""

    event_name: ClassVar[str] = "digest.unified.completed"

    subject: str
    build_session_id: str
    doc_count: int
    chunk_count: int
    new_node_count: int
    new_edge_count: int
    curriculum_ready: bool
    elapsed_ms: int
    occurred_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class UnifiedBuildFailedEvent:
    """Unified digest build failed."""

    event_name: ClassVar[str] = "digest.unified.failed"

    subject: str
    build_session_id: str
    error_message: str
    occurred_at: datetime = field(default_factory=utcnow)
