"""Workflow graph export metadata for diagram generation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True, frozen=True)
class WorkflowGraphExport:
    """A workflow graph that can be rendered directly from LangGraph."""

    key: str
    title: str
    description: str
    build_graph: Callable[[], Any]
