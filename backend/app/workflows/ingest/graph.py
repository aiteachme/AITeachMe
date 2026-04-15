"""Module-level ingest graph exports.

The canonical graph implementations now live under the chain packages:

- `ingest.fast_parse.graph`
- `ingest.deep_enhance.graph`

This module only preserves the stable import surface that older callers still
use today.
"""

from __future__ import annotations

from langgraph.graph import StateGraph

from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.ingest.deep_enhance.graph import (
    build_deep_enhance_graph,
    get_langgraph_dev_deep_enhance_graph,
)
from app.workflows.ingest.fast_parse.graph import (
    build_fast_parse_graph,
    get_langgraph_dev_fast_parse_graph,
)


def build_parse_file_graph(*, context: WorkflowContext) -> StateGraph:
    """Legacy alias for the fast-parse chain graph."""

    return build_fast_parse_graph(context=context)


__all__ = [
    "build_deep_enhance_graph",
    "build_fast_parse_graph",
    "build_parse_file_graph",
    "get_langgraph_dev_deep_enhance_graph",
    "get_langgraph_dev_fast_parse_graph",
]
