"""In-memory mailbox for single-process unified digest builds."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from uuid import uuid4

from app.utils.time import utcnow
from app.workflows.digest.common.models import SharedInputs
from app.workflows.digest.unified.models import (
    ChapterPriors,
    MaterializedSections,
    TopicAnchorSnapshot,
)


@dataclass(slots=True)
class UnifiedBuildSession:
    """Single-process unified build mailbox."""

    build_session_id: str
    subject: str
    file_ids: list[int]
    created_at: datetime
    shared_inputs: SharedInputs
    materialized: MaterializedSections
    chapter_priors: ChapterPriors | None = None
    topic_anchor_snapshot: TopicAnchorSnapshot | None = None
    chapter_priors_event: asyncio.Event = field(default_factory=asyncio.Event)
    topic_anchor_snapshot_event: asyncio.Event = field(default_factory=asyncio.Event)

    def publish_chapter_priors(self, priors: ChapterPriors) -> None:
        """Publish docs-to-graph chapter priors."""

        self.chapter_priors = priors
        self.chapter_priors_event.set()

    async def wait_for_chapter_priors(self, timeout_ms: int) -> ChapterPriors | None:
        """Wait briefly for docs-to-graph priors."""

        if self.chapter_priors is not None:
            return self.chapter_priors
        try:
            await asyncio.wait_for(self.chapter_priors_event.wait(), timeout_ms / 1000.0)
        except asyncio.TimeoutError:
            return None
        return self.chapter_priors

    def publish_topic_anchor_snapshot(self, snapshot: TopicAnchorSnapshot) -> None:
        """Publish graph-to-doc topic anchors."""

        self.topic_anchor_snapshot = snapshot
        self.topic_anchor_snapshot_event.set()

    async def wait_for_topic_anchor_snapshot(
        self,
        timeout_ms: int,
    ) -> TopicAnchorSnapshot | None:
        """Wait briefly for graph-to-doc topic anchors."""

        if self.topic_anchor_snapshot is not None:
            return self.topic_anchor_snapshot
        try:
            await asyncio.wait_for(
                self.topic_anchor_snapshot_event.wait(),
                timeout_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            return None
        return self.topic_anchor_snapshot


_SESSIONS: dict[str, UnifiedBuildSession] = {}
_LOCK = RLock()


def create_unified_build_session(
    *,
    subject: str,
    file_ids: list[int],
    shared_inputs: SharedInputs,
    materialized: MaterializedSections,
) -> UnifiedBuildSession:
    """Create and register a new unified build session."""

    session = UnifiedBuildSession(
        build_session_id=materialized.build_session_id or uuid4().hex,
        subject=subject,
        file_ids=file_ids,
        created_at=utcnow(),
        shared_inputs=shared_inputs,
        materialized=materialized,
    )
    with _LOCK:
        _SESSIONS[session.build_session_id] = session
    return session


def get_unified_build_session(build_session_id: str) -> UnifiedBuildSession:
    """Return a registered unified build session."""

    with _LOCK:
        session = _SESSIONS.get(build_session_id)
    if session is None:
        raise KeyError(f"Unknown unified build session: {build_session_id}")
    return session


def pop_unified_build_session(build_session_id: str) -> UnifiedBuildSession | None:
    """Drop a unified build session from the registry."""

    with _LOCK:
        return _SESSIONS.pop(build_session_id, None)

