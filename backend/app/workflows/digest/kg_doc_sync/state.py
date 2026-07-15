"""State model for docs-sync workflow."""

from __future__ import annotations

from typing import TypedDict

from app.workflows.digest.kg_doc_sync.lib.models import (
    KnowledgeSyncExtractionPayload,
    KnowledgeSyncReport,
    KnowledgeSyncRunContext,
    SectionExtractionRecord,
)


class DocsSyncState(TypedDict, total=False):
    course_id: str
    build_group_id: str
    build_lock_phase: str
    markdown: str
    course_context: str
    structured_context: dict[str, object]
    build_revision_no: int | None
    build_session_id: str
    node_metrics: dict[str, dict[str, object]]
    prefetched_sections: list[SectionExtractionRecord]
    early_units_callback: object | None
    early_units_callback_requested: bool
    early_units_seed_complete: bool
    sync_run_context: KnowledgeSyncRunContext | None
    extraction_payload: KnowledgeSyncExtractionPayload | None
    report: KnowledgeSyncReport | None
    error: str | None


__all__ = ["DocsSyncState"]
