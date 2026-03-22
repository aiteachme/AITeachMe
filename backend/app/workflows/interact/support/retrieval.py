"""Retrieval helpers for the interact workflow."""

from __future__ import annotations

from sqlmodel import Session

from app.core.embedding import aembed_texts
from app.core.retrievers import RetrievalConfig, RetrievalPipeline, RetrievedChunk
from app.repositories.knowledge.knowledge_repo import vector_search
from app.services.presenters import require_id
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

    query_embedding = await build_query_embedding(query)
    pipeline = RetrievalPipeline(vector_search_fn=lambda embedding, current_subject, current_top_k: _vector_search(
        session=session,
        query_embedding=embedding,
        subject=current_subject,
        top_k=current_top_k,
    ))
    chunks = await pipeline.retrieve(
        query,
        subject,
        config=RetrievalConfig(
            top_k=top_k,
            similarity_threshold=similarity_threshold,
            enable_keyword=False,
            enable_rerank=False,
        ),
        query_embedding=query_embedding,
    )
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

    results = vector_search(session, query_embedding, subject, top_k=top_k)
    return [
        RetrievedChunk(
            chunk_id=require_id(result.chunk.id, "DocumentChunk.id"),
            document_id=result.chunk.document_id,
            title=result.chunk.title,
            header_path=result.chunk.header_path,
            content=result.chunk.content,
            score=result.score,
        )
        for result in results
    ]
