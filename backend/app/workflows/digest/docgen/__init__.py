"""Digest DocGen workflow package public surface with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "DocGenState",
    "PublishedDocumentBoundaryError",
    "PublishedDocumentChunkNotFoundError",
    "PublishedDocumentStaleError",
    "PublishedDocumentUnavailableError",
    "build_docgen_graph",
    "clear_course_knowledge",
    "create_docgen_initial_state",
    "get_docgen_result",
    "get_knowledge_build_runtime_result",
    "get_published_doc_chunk",
    "get_published_doc_manifest",
    "ensure_course_vector_index",
    "get_langgraph_dev_docgen_graph",
    "run_docgen_background",
    "run_docgen_workflow",
    "trigger_docgen_build",
]

_ATTR_TO_MODULE = {
    "DocGenState": "app.workflows.digest.docgen.state",
    "PublishedDocumentBoundaryError": "app.workflows.digest.docgen.lib.published_chunks",
    "PublishedDocumentChunkNotFoundError": "app.workflows.digest.docgen.lib.published_chunks",
    "PublishedDocumentStaleError": "app.workflows.digest.docgen.lib.published_chunks",
    "PublishedDocumentUnavailableError": "app.workflows.digest.docgen.lib.published_chunks",
    "build_docgen_graph": "app.workflows.digest.docgen.graph",
    "clear_course_knowledge": "app.workflows.digest.common.cleanup",
    "create_docgen_initial_state": "app.workflows.digest.docgen.graph",
    "get_docgen_result": "app.workflows.digest.docgen.lib.build_lifecycle",
    "get_knowledge_build_runtime_result": "app.workflows.digest.docgen.lib.build_lifecycle",
    "get_published_doc_chunk": "app.workflows.digest.docgen.lib.published_chunks",
    "get_published_doc_manifest": "app.workflows.digest.docgen.lib.published_chunks",
    "ensure_course_vector_index": "app.workflows.digest.docgen.nodes.sync_knowledge_graph",
    "get_langgraph_dev_docgen_graph": "app.workflows.digest.docgen.graph",
    "run_docgen_background": "app.workflows.digest.docgen.lib.build_lifecycle",
    "run_docgen_workflow": "app.workflows.digest.docgen.graph",
    "trigger_docgen_build": "app.workflows.digest.docgen.lib.build_lifecycle",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
