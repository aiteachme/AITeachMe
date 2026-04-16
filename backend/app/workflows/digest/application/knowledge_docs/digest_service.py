"""Compatibility shim for legacy docgen build imports."""

from app.workflows.digest.docgen.builds import *  # noqa: F401,F403
from app.workflows.digest.knowledge_graph.builds import (  # noqa: F401
    run_graph_build_background,
    run_graph_digest_background,
)

__all__ = [
    "get_docgen_result",
    "run_docgen_background",
    "run_graph_build_background",
    "run_graph_digest_background",
    "trigger_docgen_build",
]
