"""Backward-compatible alias for the current compose node."""

from app.workflows.digest.planner.nodes.compose_build_plan import (
    build_compose_build_plan_node as build_compose_plan_contract_node,
)

__all__ = ["build_compose_plan_contract_node"]
