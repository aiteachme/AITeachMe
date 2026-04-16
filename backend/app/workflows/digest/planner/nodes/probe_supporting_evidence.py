"""Backward-compatible alias for the current evidence probe node."""

from app.workflows.digest.planner.nodes.probe_evidence import (
    build_probe_evidence_node as build_probe_supporting_evidence_node,
)

__all__ = ["build_probe_supporting_evidence_node"]
