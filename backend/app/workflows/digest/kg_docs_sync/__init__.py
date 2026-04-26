"""Knowledge-doc sync workflow entrypoints with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "clear_subject_graph_entities",
    "explain_relation_path",
    "extract_doc_chapter_metadatas",
    "find_knowledge_path",
    "get_chunk_context",
    "get_focus_subgraph",
    "get_full_graph",
    "get_knowledge_overview",
    "get_knowledge_unit_detail",
    "get_knowledge_unit_relations",
    "get_knowledge_units",
    "KnowledgeDocSyncInput",
    "load_knowledge_doc_sync_input",
    "load_knowledge_doc_markdown",
    "resolve_graph_input_paths",
    "run_graph_docs_sync_after_doc_build",
    "run_graph_docs_sync_workflow",
]

_ATTR_TO_MODULE = {
    "clear_subject_graph_entities": "app.workflows.digest.kg_docs_sync.lib.cleanup",
    "explain_relation_path": "app.workflows.digest.kg_docs_sync.lib.query",
    "extract_doc_chapter_metadatas": "app.workflows.digest.kg_docs_sync.inputs",
    "find_knowledge_path": "app.workflows.digest.kg_docs_sync.lib.query",
    "get_chunk_context": "app.workflows.digest.kg_docs_sync.lib.query",
    "get_focus_subgraph": "app.workflows.digest.kg_docs_sync.lib.query",
    "get_full_graph": "app.workflows.digest.kg_docs_sync.lib.query",
    "get_knowledge_overview": "app.workflows.digest.kg_docs_sync.lib.overview",
    "get_knowledge_unit_detail": "app.workflows.digest.kg_docs_sync.lib.query",
    "get_knowledge_unit_relations": "app.workflows.digest.kg_docs_sync.lib.query",
    "get_knowledge_units": "app.workflows.digest.kg_docs_sync.lib.query",
    "KnowledgeDocSyncInput": "app.workflows.digest.kg_docs_sync.inputs",
    "load_knowledge_doc_sync_input": "app.workflows.digest.kg_docs_sync.inputs",
    "load_knowledge_doc_markdown": "app.workflows.digest.kg_docs_sync.inputs",
    "resolve_graph_input_paths": "app.workflows.digest.kg_docs_sync.inputs",
    "run_graph_docs_sync_after_doc_build": "app.workflows.digest.kg_docs_sync.builds",
    "run_graph_docs_sync_workflow": "app.workflows.digest.kg_docs_sync.workflow",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
