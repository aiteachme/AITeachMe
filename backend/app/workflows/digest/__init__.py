"""Digest workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "CurriculumDeriveState",
    "KGDigestState",
    "WORKFLOW_EXPORTS",
    "build_curriculum_derive_graph",
    "build_kg_digest_graph",
    "create_curriculum_derive_initial_state",
    "create_graph_digest_initial_state",
    "run_curriculum_derive_workflow",
    "run_graph_digest_workflow",
]

_ATTR_TO_MODULE = {
    "CurriculumDeriveState": "app.workflows.digest.state",
    "KGDigestState": "app.workflows.digest.state",
    "WORKFLOW_EXPORTS": "app.workflows.digest.exports",
    "build_curriculum_derive_graph": "app.workflows.digest.curriculum.graph",
    "build_kg_digest_graph": "app.workflows.digest.kg.graph",
    "create_curriculum_derive_initial_state": "app.workflows.digest.graph",
    "create_graph_digest_initial_state": "app.workflows.digest.graph",
    "run_curriculum_derive_workflow": "app.workflows.digest.graph",
    "run_graph_digest_workflow": "app.workflows.digest.graph",
}


def __getattr__(name: str):
    module_name = _ATTR_TO_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(module_name)
    value = getattr(module, name)
    globals()[name] = value
    return value
