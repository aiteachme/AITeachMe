"""Docs-sync workflow graph facade."""

from __future__ import annotations

from app.workflows.digest.kg_docs_sync.nodes import run_docs_sync_node
from app.workflows.digest.kg_docs_sync.state import DocsSyncState


def run_docs_sync_graph(initial_state: DocsSyncState) -> DocsSyncState:
    return run_docs_sync_node(initial_state)


__all__ = ["run_docs_sync_graph"]


