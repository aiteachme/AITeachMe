"""Compatibility VectorStore over the managed LlamaIndex course index.

The canonical index is now managed by ``llamaindex_index.manager``.  This
adapter remains only for older call sites that still instantiate
``ATMVectorStore`` through ``build_knowledge_retriever()``.

Key design decisions:
- ``add()`` is a no-op because writes go through the unified index manager.
- ``aquery()`` queries the LlamaIndex-managed course index, then loads chunk
  text from ``retrieval_chunk`` for compatibility with LlamaIndex nodes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from llama_index.core.schema import TextNode
from llama_index.core.vector_stores.types import (
    BasePydanticVectorStore,
    VectorStoreQuery,
    VectorStoreQueryResult,
)

from app.shared.infra.database import managed_session

logger = structlog.get_logger(__name__)


@dataclass
class _ExtractedChunk:
    """Plain data extracted from ORM inside session scope."""

    chunk_id: int
    file_id: str
    title: str
    header_path: str
    course_id: str
    content: str
    score: float


class ATMVectorStore(BasePydanticVectorStore):
    """LlamaIndex VectorStore compatibility wrapper over the managed course index."""

    course_id: str = ""
    stores_text: bool = True
    is_embedding_query: bool = True

    @classmethod
    def class_name(cls) -> str:
        return "ATMVectorStore"

    @property
    def client(self) -> Any:
        """Return None — we manage DB connections internally."""
        return None

    def add(self, nodes: list, **kwargs: Any) -> list[str]:
        """No-op: embeddings are written by the ingest pipeline."""
        return [node.node_id for node in nodes]

    def delete(self, ref_doc_id: str, **kwargs: Any) -> None:
        """No-op: deletions go through knowledge_repo directly."""

    def query(self, query: VectorStoreQuery, **kwargs: Any) -> VectorStoreQueryResult:
        """Sync query — delegates to the async implementation."""
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            raise RuntimeError(
                "Cannot call sync .query() from within a running event loop. "
                "Use .aquery() instead."
            )

        return asyncio.run(self.aquery(query, **kwargs))

    async def aquery(
        self, query: VectorStoreQuery, **kwargs: Any
    ) -> VectorStoreQueryResult:
        """Execute a vector similarity search against the course corpus."""

        from app.repositories.knowledge.knowledge_repo import get_chunks_by_ids
        from app.shared.infra.search.llamaindex_index import query_course_index

        query_embedding = query.query_embedding
        if not query_embedding or not self.course_id:
            return VectorStoreQueryResult(nodes=[], similarities=[], ids=[])

        top_k = query.similarity_top_k or 5

        hits = query_course_index(
            self.course_id,
            query_embedding,
            top_k=top_k,
        )
        if not hits:
            return VectorStoreQueryResult(nodes=[], similarities=[], ids=[])

        # Extract ALL ORM data inside session scope to avoid DetachedInstanceError.
        extracted: list[_ExtractedChunk] = []
        with managed_session() as session:
            chunk_ids = [hit.chunk_id for hit in hits]
            chunks = get_chunks_by_ids(session, chunk_ids)
            chunk_by_id = {chunk.id: chunk for chunk in chunks if chunk.id is not None}
            
            for hit in hits:
                chunk = chunk_by_id.get(hit.chunk_id)
                if chunk is None or chunk.course_id != self.course_id:
                    continue
                extracted.append(
                    _ExtractedChunk(
                        chunk_id=chunk.id,
                        file_id=chunk.file_id,
                        title=chunk.title,
                        header_path=chunk.header_path,
                        course_id=chunk.course_id,
                        content=chunk.content,
                        score=hit.score,
                    )
                )

        # Build LlamaIndex nodes from plain data (outside session)
        nodes: list[TextNode] = []
        similarities: list[float] = []
        ids: list[str] = []

        for item in extracted:
            node = TextNode(
                text=item.content,
                id_=str(item.chunk_id),
                metadata={
                    "chunk_id": item.chunk_id,
                    "file_id": item.file_id,
                    "title": item.title,
                    "header_path": item.header_path,
                    "course_id": item.course_id,
                    "source": "vector",
                },
                excluded_embed_metadata_keys=["chunk_id", "file_id", "course_id", "source"],
                excluded_llm_metadata_keys=["chunk_id", "file_id", "course_id", "source"],
            )
            nodes.append(node)
            similarities.append(item.score)
            ids.append(str(item.chunk_id))

        logger.info(
            "llamaindex_vector_query",
            course_id=self.course_id,
            top_k=top_k,
            result_count=len(nodes),
        )
        return VectorStoreQueryResult(nodes=nodes, similarities=similarities, ids=ids)


__all__ = ["ATMVectorStore"]
