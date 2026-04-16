"""Digest workflow state re-exports."""

from __future__ import annotations

from app.workflows.digest.docgen.state import DocGenState
from app.workflows.digest.knowledge_graph.state import KnowledgeDigestState

__all__ = ["DocGenState", "KnowledgeDigestState"]
