"""Knowledge retrieval primitives kept under the search namespace.

`search` in this project is broader than classic RAG:
- web retrievers discover candidate URLs and snippets
- readers extract page content from URLs
- knowledge retrieval searches the local subject corpus

This module groups the local knowledge retrieval contracts so we do not keep
similarly named retrieval files split between `infra/` root and `infra/search/`.

.. deprecated::
    ``RetrievalPipeline`` is replaced by the LlamaIndex-managed subject index
    in ``llamaindex_index/manager.py``.
    ``RetrievedChunk``, ``RetrievalConfig`` and ``rerank_chunks()`` remain
    as shared data contracts.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from app.shared.infra.settings import get_settings
from app.shared.infra.env_support import get_env

logger = structlog.get_logger()


@dataclass
class RetrievalConfig:
    top_k: int = 5
    similarity_threshold: float = 0.3
    enable_keyword: bool = False
    enable_rerank: bool = False


@dataclass
class RetrievedChunk:
    chunk_id: int
    document_id: int
    title: str
    header_path: str
    content: str
    score: float
    source: str = "vector"


class RetrievalPipeline:
    """Unified retrieval pipeline with pluggable vector / keyword / rerank hooks."""

    def __init__(self, *, vector_search_fn=None, keyword_search_fn=None, rerank_fn=None) -> None:
        self._vector = vector_search_fn
        self._keyword = keyword_search_fn
        self._rerank = rerank_fn

    async def retrieve(
        self,
        query: str,
        subject: str,
        *,
        config: RetrievalConfig | None = None,
        query_embedding: list[float] | None = None,
    ) -> list[RetrievedChunk]:
        cfg = config or RetrievalConfig()
        chunks: list[RetrievedChunk] = []

        if self._vector and query_embedding:
            results = await self._vector(query_embedding, subject, cfg.top_k)
            for chunk in results:
                chunk.source = "vector"
            chunks.extend(results)

        if cfg.enable_keyword and self._keyword:
            seen = {chunk.chunk_id for chunk in chunks}
            for chunk in await self._keyword(query, subject, cfg.top_k):
                if chunk.chunk_id not in seen:
                    chunk.source = "keyword"
                    chunks.append(chunk)

        chunks = [chunk for chunk in chunks if chunk.score >= cfg.similarity_threshold]
        if cfg.enable_rerank and self._rerank:
            chunks = await self._rerank(query, chunks)

        chunks.sort(key=lambda chunk: chunk.score, reverse=True)
        result = chunks[: cfg.top_k]
        logger.info("retrieval_done", subject=subject, returned=len(result))
        return result


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
    model = settings.rag.rerank_model
    if not model or not chunks:
        return chunks

    api_key = (get_env("RAG_RERANK_API_KEY") or get_env("LLM_API_KEY") or "").strip()
    base_url = (
        get_env("RAG_RERANK_BASE_URL")
        or get_env("LLM_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    final_top_k = top_k or settings.rag.rerank_top_k

    if not api_key:
        logger.warning("rerank_skipped_no_api_key")
        return chunks

    try:
        from app.shared.infra.llm_support.litellm_loader import load_litellm

        litellm = load_litellm()

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


__all__ = [
    "RetrievedChunk",
    "RetrievalConfig",
    "RetrievalPipeline",
    "rerank_chunks",
]
