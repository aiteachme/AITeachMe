"""Public search helpers used by the teaching stack."""

from __future__ import annotations

import structlog
from sqlmodel import Session

from app.core.config import get_settings
from app.core.database import get_engine
from app.infra.embedding import aembed_texts
from app.infra.retrievers import RetrievedChunk
from app.infra.reranker import rerank_chunks
from app.infra.search.types import WebSearchResult
from app.infra.search.web import dispatch_web_search
from app.repositories.knowledge.knowledge_repo import vector_search
from app.utils.presenters import require_id

logger = structlog.get_logger()


async def web_search(
    query: str,
    *,
    top_k: int = 5,
) -> list[WebSearchResult]:
    """Search the web with the configured provider."""

    return await dispatch_web_search(query, top_k=top_k)


async def search_knowledge(
    query: str,
    subject_id: str,
    *,
    top_k: int = 5,
    enable_rerank: bool = True,
) -> list[RetrievedChunk]:
    """Search retrieval chunks for one subject using the current schema."""

    normalized_query = query.strip()
    normalized_subject = subject_id.strip()
    if not normalized_query or not normalized_subject or top_k <= 0:
        return []

    settings = get_settings()

    try:
        query_embedding = (await aembed_texts([normalized_query]))[0]
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "search_knowledge_embedding_failed",
            subject=normalized_subject,
            error=str(exc),
        )
        return []

    fetch_top_k = top_k * 2 if enable_rerank and settings.rag_rerank_model else top_k
    chunks = await _vector_search(
        query_embedding=query_embedding,
        subject=normalized_subject,
        top_k=fetch_top_k,
    )

    if enable_rerank and chunks and settings.rag_rerank_model:
        try:
            chunks = await rerank_chunks(normalized_query, chunks, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "search_knowledge_rerank_failed",
                subject=normalized_subject,
                error=str(exc),
            )

    result = chunks[:top_k]
    logger.info(
        "knowledge_search_complete",
        subject=normalized_subject,
        query_len=len(normalized_query),
        result_count=len(result),
    )
    return result


async def _vector_search(
    *,
    query_embedding: list[float],
    subject: str,
    top_k: int,
) -> list[RetrievedChunk]:
    """Run vector search through the repository helpers."""

    if top_k <= 0:
        return []

    engine = get_engine()
    with Session(engine) as session:
        results = vector_search(session, query_embedding, subject, top_k=top_k)
        return [
            RetrievedChunk(
                chunk_id=require_id(result.chunk.id, "RetrievalChunk.id"),
                document_id=result.chunk.document_id,
                title=result.chunk.title,
                header_path=result.chunk.header_path,
                content=result.chunk.content,
                score=result.score,
                source="vector",
            )
            for result in results
        ]
