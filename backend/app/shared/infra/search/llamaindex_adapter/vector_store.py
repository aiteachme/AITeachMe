"""Bridge existing sqlite-vec / pgvector storage to LlamaIndex VectorStore.

This adapter wraps the raw SQL-based ``knowledge_repo.vector_search()``
behind the ``BasePydanticVectorStore`` interface so that a
``VectorStoreIndex`` can be created without changing the underlying
database schema.

Key design decisions:
- ``add()`` is a no-op: embeddings are written through the existing
  ``bulk_insert_embeddings()`` pipeline in the ingest/digest workflows.
  We only bridge the *read* (query) path here.
- ``aquery()`` opens its own DB session via ``managed_session()`` and
  extracts all ORM data **inside** the session scope to avoid
  ``DetachedInstanceError`` on both SQLite and PostgreSQL.
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
    document_id: int
    title: str
    header_path: str
    subject: str
    content: str
    score: float


class ATMVectorStore(BasePydanticVectorStore):
    """LlamaIndex VectorStore backed by the existing sqlite-vec / pgvector tables."""

    subject: str = ""
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
            import nest_asyncio

            nest_asyncio.apply()
            return loop.run_until_complete(self.aquery(query, **kwargs))

        return asyncio.get_event_loop().run_until_complete(
            self.aquery(query, **kwargs)
        )

    async def aquery(
        self, query: VectorStoreQuery, **kwargs: Any
    ) -> VectorStoreQueryResult:
        """Execute a vector similarity search against the subject corpus."""

        from app.repositories.knowledge.knowledge_repo import vector_search

        query_embedding = query.query_embedding
        if not query_embedding or not self.subject:
            return VectorStoreQueryResult(nodes=[], similarities=[], ids=[])

        top_k = query.similarity_top_k or 5

        # Extract ALL ORM data inside session scope to avoid
        # DetachedInstanceError on both SQLite and PostgreSQL.
        extracted: list[_ExtractedChunk] = []
        with managed_session() as session:
            results = vector_search(
                session,
                query_embedding,
                self.subject,
                top_k=top_k,
            )
            for result in results:
                chunk = result.chunk
                if chunk.id is None:
                    continue
                extracted.append(
                    _ExtractedChunk(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        title=chunk.title,
                        header_path=chunk.header_path,
                        subject=chunk.subject,
                        content=chunk.content,
                        score=result.score,
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
                    "document_id": item.document_id,
                    "title": item.title,
                    "header_path": item.header_path,
                    "subject": item.subject,
                    "source": "vector",
                },
                excluded_embed_metadata_keys=["chunk_id", "document_id", "subject", "source"],
                excluded_llm_metadata_keys=["chunk_id", "document_id", "subject", "source"],
            )
            nodes.append(node)
            similarities.append(item.score)
            ids.append(str(item.chunk_id))

        logger.info(
            "llamaindex_vector_query",
            subject=self.subject,
            top_k=top_k,
            result_count=len(nodes),
        )
        return VectorStoreQueryResult(nodes=nodes, similarities=similarities, ids=ids)


__all__ = ["ATMVectorStore"]
