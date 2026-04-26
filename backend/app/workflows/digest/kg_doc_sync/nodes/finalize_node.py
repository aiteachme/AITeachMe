"""Docs-sync finalize node."""

from __future__ import annotations

from app.workflows.digest.kg_doc_sync.state import DocsSyncState


def finalize_node(state: DocsSyncState) -> DocsSyncState:
    if state.get("report") is None and not state.get("error"):
        return {**state, "error": "docs_sync_report_missing"}
    return state


__all__ = ["finalize_node"]

