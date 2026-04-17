"""Docs-sync execution node."""

from __future__ import annotations

from app.shared.infra.database import managed_session
from app.workflows.digest.kg_docs_sync.state import DocsSyncState
from app.workflows.support.knowledge_graph.incremental_sync import sync_markdown_knowledge_graph


def run_docs_sync_node(state: DocsSyncState) -> DocsSyncState:
    try:
        with managed_session() as session:
            report = sync_markdown_knowledge_graph(
                session,
                subject=state["subject"],
                markdown=state["markdown"],
                build_revision_no=state.get("build_revision_no"),
            )
        return {**state, "report": report, "error": None}
    except Exception as exc:
        return {**state, "report": None, "error": str(exc)}


__all__ = ["run_docs_sync_node"]



