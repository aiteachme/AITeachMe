"""Vector retrieval for the chat engine."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlmodel import Session

from app.core.config import get_settings
from app.core.embedding import aembed_texts
from app.repositories.knowledge_repo import ChunkSearchResult, vector_search
from app.services.presenters import require_id

logger = structlog.get_logger()


@dataclass
class RetrievalResult:
    chunk_id: int
    document_id: int
    title: str
    header_path: str
    content: str
    score: float
    low_relevance: bool


async def retrieve(
    session: Session,
    query: str,
    subject: str,
    *,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
) -> list[RetrievalResult]:
    settings = get_settings()
    top_k = top_k or settings.rag_top_k
    similarity_threshold = (
        similarity_threshold
        if similarity_threshold is not None
        else settings.rag_similarity_threshold
    )

    query_embedding = (await aembed_texts([query]))[0]
    search_results: list[ChunkSearchResult] = vector_search(
        session,
        query_embedding,
        subject,
        top_k=top_k,
    )

    results = [
        RetrievalResult(
            chunk_id=require_id(result.chunk.id, "DocumentChunk.id"),
            document_id=result.chunk.document_id,
            title=result.chunk.title,
            header_path=result.chunk.header_path,
            content=result.chunk.content,
            score=result.score,
            low_relevance=result.score < similarity_threshold,
        )
        for result in search_results
    ]

    logger.info(
        "retrieval_complete",
        subject=subject,
        query_len=len(query),
        num_results=len(results),
        all_low_relevance=all(item.low_relevance for item in results) if results else True,
    )
    return results
