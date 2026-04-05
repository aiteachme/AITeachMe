"""Workflow graph export metadata for diagram generation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True, frozen=True)
class WorkflowGraphExport:
    """A workflow graph that can be rendered directly from LangGraph."""

    key: str
    title: str
    description: str
    build_graph: Callable[[], Any]
    # Send 动态边无法被 draw_mermaid 自动导出，
    # 在此声明需要注入的额外边（格式："src --> dst" 或 "src -. label .-> dst"）
    extra_edges: tuple[str, ...] = field(default=())
    prompts: dict[str, str] = field(default_factory=dict)


