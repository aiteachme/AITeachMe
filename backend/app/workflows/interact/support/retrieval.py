"""Retrieval helpers for the interact workflow."""

from __future__ import annotations

from sqlmodel import Session

from app.core.config import get_settings
from app.infra.embedding import aembed_texts
from app.infra.reranker import rerank_chunks
from app.infra.retrievers import RetrievalConfig, RetrievalPipeline, RetrievedChunk
from app.repositories.knowledge.knowledge_repo import vector_search
from app.utils.presenters import require_id
from app.workflows.interact.support.types import RetrievedContext


async def build_query_embedding(query: str) -> list[float]:
    """Build the vector embedding used for retrieval."""

    return (await aembed_texts([query]))[0]


async def retrieve_context(
    *,
    session: Session,
    query: str,
    subject: str,
    top_k: int,
    similarity_threshold: float,
) -> list[RetrievedContext]:
    """Retrieve prompt-ready context chunks for one chat question."""

    normalized_query = query.strip()
    if not normalized_query or top_k <= 0:
        return []

    settings = get_settings()
    enable_rerank = bool(settings.rag_rerank_model)

    query_embedding = await build_query_embedding(normalized_query)
    pipeline = RetrievalPipeline(
        vector_search_fn=lambda embedding, current_subject, current_top_k: _vector_search(
            session=session,
            query_embedding=embedding,
            subject=current_subject,
            top_k=current_top_k,
        ),
        rerank_fn=rerank_chunks if enable_rerank else None,
    )
    # When reranking, fetch more candidates for better recall
    fetch_top_k = top_k * 3 if enable_rerank else top_k
    chunks = await pipeline.retrieve(
        normalized_query,
        subject,
        config=RetrievalConfig(
            top_k=fetch_top_k,
            similarity_threshold=similarity_threshold,
            enable_keyword=False,
            enable_rerank=enable_rerank,
        ),
        query_embedding=query_embedding,
    )
    # After rerank, trim to requested top_k
    chunks = chunks[:top_k]
    return [
        RetrievedContext(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            title=chunk.title,
            header_path=chunk.header_path,
            content=chunk.content,
            score=chunk.score,
            low_relevance=chunk.score < similarity_threshold,
        )
        for chunk in chunks
    ]


async def _vector_search(
    *,
    session: Session,
    query_embedding: list[float],
    subject: str,
    top_k: int,
) -> list[RetrievedChunk]:
    """Adapt repository vector search to the shared retrieval pipeline."""

    if top_k <= 0:
        return []

    results = vector_search(session, query_embedding, subject, top_k=top_k)
    return [
        RetrievedChunk(
            chunk_id=require_id(result.chunk.id, "RetrievalChunk.id"),
            document_id=result.chunk.document_id,
            title=result.chunk.title,
            header_path=result.chunk.header_path,
            content=result.chunk.content,
            score=result.score,
        )
        for result in results
    ]
