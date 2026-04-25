"""State model for docs-sync workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

if TYPE_CHECKING:
    from app.workflows.support.knowledge_graph.incremental_sync import KnowledgeSyncReport


class DocsSyncState(TypedDict, total=False):
    subject: str
    markdown: str
    subject_context: str
    build_revision_no: int | None
    build_session_id: str
    report: KnowledgeSyncReport | None
    error: str | None


__all__ = ["DocsSyncState"]
