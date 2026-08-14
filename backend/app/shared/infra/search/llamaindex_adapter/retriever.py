"""High-level LlamaIndex retriever and factory for the ATM knowledge base.

This module assembles the adapter components (ATMEmbedding, ATMVectorStore,
ATMReranker) into a ready-to-use LlamaIndex retriever that can be called
from workflow nodes.

Usage::

    retriever = build_knowledge_retriever(course_id="course_math101", top_k=5)
    nodes = await retriever.aretrieve("什么是微积分？")
"""

from __future__ import annotations

import structlog
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import NodeWithScore, QueryBundle

from app.models.course import Course
from app.shared.infra.database import managed_session
from app.shared.infra.settings import get_settings
from app.shared.infra.embedding import ATMEmbedding
from app.shared.infra.search.llamaindex_adapter.reranker import ATMReranker
from app.shared.infra.search.llamaindex_adapter.vector_store import ATMVectorStore
from app.shared.infra.course.settings import get_course_embedding_binding
from sqlmodel import select

logger = structlog.get_logger(__name__)


class ATMKnowledgeRetriever:
    """Convenience wrapper: VectorIndexRetriever + optional ATMReranker.

    This is **not** a LlamaIndex ``BaseRetriever`` subclass — it is a
    thin orchestrator that owns the index, retriever, and postprocessor
    lifecycle so callers just need ``await retriever.aretrieve(query)``.
    """

    def __init__(
        self,
        *,
        course_id: str,
        top_k: int = 5,
        enable_rerank: bool | None = None,
    ) -> None:
        self.course_id = course_id
        self.top_k = top_k

        settings = get_settings()
        self._enable_rerank = (
            enable_rerank
            if enable_rerank is not None
            else settings.rerank_configured
        )

        # Build LlamaIndex components
        binding_model: str | None = None
        with managed_session() as session:
            course_row = session.exec(
                select(Course).where(Course.id == course_id)
            ).first()
            if course_row is not None:
                binding = get_course_embedding_binding(course_row)
                if binding is not None:
                    binding_model = binding.embedding_model
        self._embed_model = ATMEmbedding(model_name=binding_model)
        self._vector_store = ATMVectorStore(course_id=course_id)
        self._index = VectorStoreIndex.from_vector_store(
            vector_store=self._vector_store,
            embed_model=self._embed_model,
        )

        # Fetch more candidates when reranking for better recall
        fetch_top_k = top_k * 3 if self._enable_rerank else top_k
        self._retriever = self._index.as_retriever(
            similarity_top_k=fetch_top_k,
        )

        self._reranker: ATMReranker | None = None
        if self._enable_rerank:
            rerank_top_n = min(top_k, settings.rag.rerank_top_k or top_k)
            self._reranker = ATMReranker(top_n=rerank_top_n)

    async def aretrieve(self, query: str) -> list[NodeWithScore]:
        """Retrieve and optionally rerank nodes for one query."""

        nodes = await self._retriever.aretrieve(query)

        if self._reranker and nodes:
            query_bundle = QueryBundle(query_str=query)
            nodes = await self._reranker._apostprocess_nodes(nodes, query_bundle)

        # Final trim to requested top_k
        return nodes[: self.top_k]

    def retrieve(self, query: str) -> list[NodeWithScore]:
        """Sync fallback."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            raise RuntimeError(
                "Cannot call sync retrieve() from within a running event loop. "
                "Use aretrieve() instead."
            )

        return asyncio.run(self.aretrieve(query))


def build_knowledge_retriever(
    course_id: str,
    *,
    top_k: int = 5,
    enable_rerank: bool | None = None,
) -> ATMKnowledgeRetriever:
    """Factory: create a ready-to-use knowledge retriever for one course.

    Args:
        course_id: The course ID to search within.
        top_k: Number of final results to return.
        enable_rerank: Override rerank behaviour. ``None`` means auto-detect
            from runtime settings (``models.rerank``).

    Returns:
        An ``ATMKnowledgeRetriever`` instance.
    """
    return ATMKnowledgeRetriever(
        course_id=course_id,
        top_k=top_k,
        enable_rerank=enable_rerank,
    )


__all__ = ["ATMKnowledgeRetriever", "build_knowledge_retriever"]
