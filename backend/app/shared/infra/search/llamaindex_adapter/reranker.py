"""Bridge existing litellm rerank to LlamaIndex NodePostprocessor.

Wraps the ``rerank_chunks()`` helper (which calls ``litellm.arerank()``)
as a LlamaIndex ``BaseNodePostprocessor`` so it can be inserted into a
retriever pipeline chain.
"""

from __future__ import annotations

from typing import Optional

import structlog
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import MetadataMode, NodeWithScore, QueryBundle

from app.shared.infra.settings import get_settings
from app.shared.infra.search.knowledge import RetrievedChunk, rerank_chunks

logger = structlog.get_logger(__name__)


class ATMReranker(BaseNodePostprocessor):
    """LlamaIndex postprocessor backed by litellm rerank."""

    top_n: int = 3

    @classmethod
    def class_name(cls) -> str:
        return "ATMReranker"

    def _postprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> list[NodeWithScore]:
        """Sync fallback — should rarely be hit in async FastAPI."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            raise RuntimeError(
                "Cannot call sync _postprocess_nodes() from within a running event loop. "
                "Use _apostprocess_nodes() instead."
            )

        return asyncio.run(self._apostprocess_nodes(nodes, query_bundle))

    async def _apostprocess_nodes(
        self,
        nodes: list[NodeWithScore],
        query_bundle: Optional[QueryBundle] = None,
    ) -> list[NodeWithScore]:
        """Run litellm rerank and return re-scored nodes."""

        settings = get_settings()
        if not settings.rerank_configured or not nodes:
            return nodes

        query_str = query_bundle.query_str if query_bundle else ""
        if not query_str:
            return nodes

        # Convert LlamaIndex nodes → RetrievedChunk for rerank_chunks()
        chunks: list[RetrievedChunk] = []
        node_map: dict[int, NodeWithScore] = {}
        for idx, node_with_score in enumerate(nodes):
            node = node_with_score.node
            metadata = node.metadata or {}
            chunk = RetrievedChunk(
                chunk_id=int(metadata.get("chunk_id", idx)),
                file_id=str(metadata.get("file_id") or metadata.get("document_id") or ""),
                title=str(metadata.get("title", "")),
                header_path=str(metadata.get("header_path", "")),
                content=node.get_content(metadata_mode=MetadataMode.NONE),
                score=node_with_score.score or 0.0,
                source=str(metadata.get("source", "vector")),
            )
            # Store original index dynamically
            setattr(chunk, "_node_idx", idx)
            chunks.append(chunk)
            node_map[idx] = node_with_score

        reranked = await rerank_chunks(
            query_str,
            chunks,
            top_k=self.top_n,
        )

        # Build reranked NodeWithScore list with updated scores
        result: list[NodeWithScore] = []
        for chunk in reranked:
            original_node = node_map.get(getattr(chunk, "_node_idx", -1))
            if original_node is None:
                continue
            # Update score and source metadata
            original_node.score = chunk.score
            if original_node.node.metadata:
                original_node.node.metadata["source"] = chunk.source
            result.append(original_node)

        logger.info(
            "llamaindex_rerank_done",
            input_count=len(nodes),
            output_count=len(result),
            model=settings.models.rerank,
        )
        return result


__all__ = ["ATMReranker"]
