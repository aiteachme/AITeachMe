"""Internal helpers for optional workflow diagram exports.

These types are not part of the normal workflow authoring surface.
They only exist for offline documentation / diagram generation scripts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class WorkflowGraphExport:
    """Describe one graph for offline diagram/document generation."""

    key: str
    title: str
    description: str
    build_graph: Callable[[], Any]
    # Dynamic edges are not exported by ``draw_mermaid`` automatically.
    # Declare any manual Mermaid edges here, for example:
    # ``"src --> dst"`` or ``"src -. label .-> dst"``.
    extra_edges: tuple[str, ...] = field(default=())
    prompts: dict[str, str] = field(default_factory=dict)


__all__ = ["WorkflowGraphExport"]
