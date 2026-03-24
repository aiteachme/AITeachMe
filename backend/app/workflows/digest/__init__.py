"""Digest workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "CurriculumDeriveState",
    "DocGenState",
    "KGDigestState",
    "WORKFLOW_EXPORTS",
    "build_curriculum_derive_graph",
    "build_docgen_graph",
    "build_kg_digest_graph",
    "build_unified_digest_graph",
    "create_curriculum_derive_initial_state",
    "create_docgen_initial_state",
    "create_graph_digest_initial_state",
    "create_unified_initial_state",
    "run_curriculum_derive_workflow",
    "run_docgen_workflow",
    "run_graph_digest_workflow",
    "run_unified_digest_build",
]

_ATTR_TO_MODULE = {
    "CurriculumDeriveState": "app.workflows.digest.state",
    "DocGenState": "app.workflows.digest.state",
    "KGDigestState": "app.workflows.digest.state",
    "WORKFLOW_EXPORTS": "app.workflows.digest.exports",
    "build_curriculum_derive_graph": "app.workflows.digest.graph",
    "build_docgen_graph": "app.workflows.digest.graph",
    "build_kg_digest_graph": "app.workflows.digest.graph",
    "build_unified_digest_graph": "app.workflows.digest.unified.graph",
    "create_curriculum_derive_initial_state": "app.workflows.digest.runtime",
    "create_docgen_initial_state": "app.workflows.digest.runtime",
    "create_graph_digest_initial_state": "app.workflows.digest.runtime",
    "create_unified_initial_state": "app.workflows.digest.unified.graph",
    "run_curriculum_derive_workflow": "app.workflows.digest.runtime",
    "run_docgen_workflow": "app.workflows.digest.runtime",
    "run_graph_digest_workflow": "app.workflows.digest.runtime",
    "run_unified_digest_build": "app.workflows.digest.unified.runtime",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
