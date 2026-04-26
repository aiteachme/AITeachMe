"""Docs-sync fail node."""

from __future__ import annotations

from app.workflows.digest.kg_doc_sync.state import DocsSyncState


def fail_node(state: DocsSyncState) -> DocsSyncState:
    return state


__all__ = ["fail_node"]

