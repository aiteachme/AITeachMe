"""Compatibility exports for local knowledge retrieval contracts."""

from app.shared.infra.search.knowledge import RetrievalConfig, RetrievalPipeline, RetrievedChunk

__all__ = ["RetrievedChunk", "RetrievalConfig", "RetrievalPipeline"]
