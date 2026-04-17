"""Docs-sync prepare node."""

from __future__ import annotations

from app.workflows.digest.kg_docs_sync.state import DocsSyncState


def prepare_node(state: DocsSyncState) -> DocsSyncState:
    subject = str(state.get("subject") or "").strip()
    markdown = str(state.get("markdown") or "")
    if not subject:
        return {**state, "error": "docs_sync_missing_subject"}
    if not markdown.strip():
        return {**state, "error": "docs_sync_missing_markdown"}
    return {**state, "subject": subject, "error": None}


__all__ = ["prepare_node"]

