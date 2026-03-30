"""Rerank service for RAG retrieval pipeline.

Uses a configurable rerank model to re-score retrieved chunks
for better relevance ordering.
"""

from __future__ import annotations

import structlog

from app.core.config import get_settings
from app.infra.retrievers import RetrievedChunk

logger = structlog.get_logger()


async def rerank_chunks(
    query: str,
    chunks: list[RetrievedChunk],
    *,
    top_k: int | None = None,
) -> list[RetrievedChunk]:
    """Rerank retrieved chunks using the configured rerank model.

    Falls back to original ordering if rerank is not configured or fails.
    """

    settings = get_settings()
    model = settings.rag_rerank_model
    if not model or not chunks:
        return chunks

    api_key = settings.rag_rerank_api_key or settings.llm_api_key
    base_url = settings.rag_rerank_base_url or settings.llm_base_url
    final_top_k = top_k or settings.rag_rerank_top_k

    if not api_key:
        logger.warning("rerank_skipped_no_api_key")
        return chunks

    try:
        import litellm

        documents = [chunk.content[:2000] for chunk in chunks]
        response = await litellm.arerank(
            model=model,
            query=query,
            documents=documents,
            top_n=min(final_top_k, len(documents)),
            api_key=api_key,
            api_base=base_url,
        )

        reranked: list[RetrievedChunk] = []
        for result in response.results:
            idx = result.index
            if 0 <= idx < len(chunks):
                chunk = chunks[idx]
                chunk.score = float(result.relevance_score)
                chunk.source = f"{chunk.source}+rerank"
                reranked.append(chunk)

        logger.info(
            "rerank_completed",
            model=model,
            input_count=len(chunks),
            output_count=len(reranked),
        )
        return reranked

    except Exception as exc:
        logger.warning("rerank_failed_fallback", error=str(exc), model=model)
        return chunks[:final_top_k]
