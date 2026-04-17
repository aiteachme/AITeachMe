"""State model for docs-sync workflow."""

from __future__ import annotations

from typing import TypedDict

from app.workflows.support.knowledge_graph.incremental_sync import KnowledgeSyncReport


class DocsSyncState(TypedDict, total=False):
    subject: str
    markdown: str
    build_revision_no: int | None
    report: KnowledgeSyncReport | None
    error: str | None


__all__ = ["DocsSyncState"]


