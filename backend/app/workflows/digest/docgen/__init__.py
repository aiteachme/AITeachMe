"""Digest DocGen sub-workflow.

Stable public surface:

- `DocGenState`
- `build_docgen_graph`
- `create_docgen_initial_state`
- `get_langgraph_dev_docgen_graph`

Implementation details such as concrete node builders stay inside
`docgen.graph`, `docgen.nodes`, `docgen.prompts`, and `docgen.lib`.
"""

from app.workflows.digest.docgen.graph import (
    build_docgen_graph,
    create_docgen_initial_state,
    get_langgraph_dev_docgen_graph,
)
from app.workflows.digest.docgen.state import DocGenState

__all__ = [
    "DocGenState",
    "build_docgen_graph",
    "create_docgen_initial_state",
    "get_langgraph_dev_docgen_graph",
]
