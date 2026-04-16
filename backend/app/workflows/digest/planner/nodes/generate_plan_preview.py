"""Backward-compatible alias for the current preview/bootstrap node."""

from app.workflows.digest.planner.nodes.bootstrap_plan_brief import (
    build_bootstrap_plan_brief_node as build_generate_plan_preview_node,
)

__all__ = ["build_generate_plan_preview_node"]
