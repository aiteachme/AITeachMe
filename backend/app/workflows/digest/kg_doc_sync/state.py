"""State model for docs-sync workflow."""

from __future__ import annotations

from typing import TypedDict

from app.workflows.digest.kg_doc_sync.lib.incremental_sync import KnowledgeSyncReport


class DocsSyncState(TypedDict, total=False):
    subject: str
    markdown: str
    subject_context: str
    structured_context: dict[str, object]
    build_revision_no: int | None
    build_session_id: str
    report: KnowledgeSyncReport | None
    error: str | None


__all__ = ["DocsSyncState"]
