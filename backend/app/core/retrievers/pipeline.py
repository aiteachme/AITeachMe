"""统一检索管线：向量 + 关键词 + rerank。"""
from __future__ import annotations
import structlog
from app.core.retrievers.types import RetrievalConfig, RetrievedChunk

logger = structlog.get_logger()

class RetrievalPipeline:
    def __init__(self, *, vector_search_fn=None, keyword_search_fn=None, rerank_fn=None) -> None:
        self._vector_search = vector_search_fn
        self._keyword_search = keyword_search_fn
        self._rerank = rerank_fn

    async def retrieve(self, query: str, subject: str, *, config: RetrievalConfig | None = None,
                       query_embedding: list[float] | None = None) -> list[RetrievedChunk]:
        cfg = config or RetrievalConfig()
        all_chunks: list[RetrievedChunk] = []

        if self._vector_search and query_embedding:
            results = await self._vector_search(query_embedding, subject, cfg.top_k)
            for c in results: c.source = "vector"
            all_chunks.extend(results)

        if cfg.enable_keyword_search and self._keyword_search:
            results = await self._keyword_search(query, subject, cfg.top_k)
            seen = {c.chunk_id for c in all_chunks}
            for c in results:
                if c.chunk_id not in seen:
                    c.source = "keyword"; all_chunks.append(c); seen.add(c.chunk_id)

        all_chunks = [c for c in all_chunks if c.score >= cfg.similarity_threshold]

        if cfg.enable_rerank and self._rerank:
            all_chunks = await self._rerank(query, all_chunks)

        all_chunks.sort(key=lambda c: c.score, reverse=True)
        result = all_chunks[:cfg.top_k]
        logger.info("retrieval_complete", query_len=len(query), subject=subject, returned=len(result))
        return result
