"""Compatibility shim for legacy digest runtime imports."""

from app.workflows.digest.docgen import create_docgen_initial_state, run_docgen_workflow
from app.workflows.digest.knowledge_graph import (
    create_graph_digest_initial_state,
    run_graph_digest_workflow,
)

__all__ = [
    "create_docgen_initial_state",
    "create_graph_digest_initial_state",
    "run_docgen_workflow",
    "run_graph_digest_workflow",
]
