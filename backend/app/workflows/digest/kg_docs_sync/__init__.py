"""Knowledge-doc sync workflow entrypoints with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "extract_doc_chapter_metadatas",
    "KnowledgeDocSyncInput",
    "load_knowledge_doc_sync_input",
    "load_knowledge_doc_markdown",
    "resolve_graph_input_paths",
    "run_graph_docs_sync_workflow",
]

_ATTR_TO_MODULE = {
    "extract_doc_chapter_metadatas": "app.workflows.digest.kg_docs_sync.inputs",
    "KnowledgeDocSyncInput": "app.workflows.digest.kg_docs_sync.inputs",
    "load_knowledge_doc_sync_input": "app.workflows.digest.kg_docs_sync.inputs",
    "load_knowledge_doc_markdown": "app.workflows.digest.kg_docs_sync.inputs",
    "resolve_graph_input_paths": "app.workflows.digest.kg_docs_sync.inputs",
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
