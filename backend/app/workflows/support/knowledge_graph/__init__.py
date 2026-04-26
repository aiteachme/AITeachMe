"""Support knowledge-graph business module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.workflows.support.knowledge_graph.cleanup import clear_subject_graph_entities
from app.workflows.support.knowledge_graph.builds import (
    run_graph_docs_sync_after_doc_build,
    run_graph_file_ingest_background,
)
from app.workflows.support.knowledge_graph.incremental_sync import (
    KnowledgeSyncReport,
    sync_markdown_knowledge_graph,
)
from app.workflows.support.knowledge_graph.overview import get_knowledge_overview
from app.workflows.support.knowledge_graph.query import (
    explain_relation_path,
    find_knowledge_path,
    get_chunk_context,
    get_focus_subgraph,
    get_full_graph,
    get_knowledge_unit_detail,
    get_knowledge_unit_relations,
    get_knowledge_units,
)

if TYPE_CHECKING:
    from app.workflows.digest.kg_docs_sync import run_graph_docs_sync_workflow
    from app.workflows.digest.kg_file_ingest import run_graph_file_ingest_workflow


def __getattr__(name: str) -> object:
    if name == "run_graph_docs_sync_workflow":
        from app.workflows.digest.kg_docs_sync import run_graph_docs_sync_workflow

        return run_graph_docs_sync_workflow
    if name == "run_graph_file_ingest_workflow":
        from app.workflows.digest.kg_file_ingest import run_graph_file_ingest_workflow

        return run_graph_file_ingest_workflow
    raise AttributeError(name)


__all__ = [
    "KnowledgeSyncReport",
    "clear_subject_graph_entities",
    "explain_relation_path",
    "find_knowledge_path",
    "get_chunk_context",
    "get_focus_subgraph",
    "get_full_graph",
    "get_knowledge_overview",
    "get_knowledge_unit_detail",
    "get_knowledge_unit_relations",
    "get_knowledge_units",
    "run_graph_docs_sync_after_doc_build",
    "run_graph_file_ingest_background",
    "run_graph_docs_sync_workflow",
    "run_graph_file_ingest_workflow",
    "sync_markdown_knowledge_graph",
]
