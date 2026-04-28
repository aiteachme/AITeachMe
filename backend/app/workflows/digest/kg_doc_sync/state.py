"""State model for docs-sync workflow."""

from __future__ import annotations

from typing import TypedDict

from app.workflows.digest.kg_doc_sync.lib.models import (
    KnowledgeSyncExtractionPayload,
    KnowledgeSyncReport,
    KnowledgeSyncRunContext,
)


class DocsSyncState(TypedDict, total=False):
    subject_id: str
    markdown: str
    subject_context: str
    structured_context: dict[str, object]
    build_revision_no: int | None
    build_session_id: str
    node_metrics: dict[str, dict[str, object]]
    sync_run_context: KnowledgeSyncRunContext | None
    extraction_payload: KnowledgeSyncExtractionPayload | None
    report: KnowledgeSyncReport | None
    error: str | None


__all__ = ["DocsSyncState"]
