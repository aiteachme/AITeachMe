"""Digest workflow package with lazy exports."""

from __future__ import annotations

from importlib import import_module

__all__ = [
    "CURRICULUM_DERIVE_DIAGRAM",
    "CurriculumDeriveState",
    "KG_DIGEST_DIAGRAM",
    "KGDigestState",
    "WORKFLOW_DIAGRAMS",
    "create_curriculum_derive_initial_state",
    "create_graph_digest_initial_state",
    "run_curriculum_derive_workflow",
    "run_graph_digest_workflow",
]

_ATTR_TO_MODULE = {
    "CURRICULUM_DERIVE_DIAGRAM": "app.workflows.digest.diagrams",
    "CurriculumDeriveState": "app.workflows.digest.state",
    "KG_DIGEST_DIAGRAM": "app.workflows.digest.diagrams",
    "KGDigestState": "app.workflows.digest.state",
    "WORKFLOW_DIAGRAMS": "app.workflows.digest.diagrams",
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
