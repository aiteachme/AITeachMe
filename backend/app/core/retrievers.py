"""统一检索管线。

支持：向量检索、关键词检索、混合检索、rerank。
通过注入 search 函数适配不同数据源。
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

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
    """统一检索管线，通过依赖注入适配不同数据源。"""

    def __init__(self, *, vector_search_fn=None, keyword_search_fn=None, rerank_fn=None) -> None:
        self._vector = vector_search_fn
        self._keyword = keyword_search_fn
        self._rerank = rerank_fn

    async def retrieve(self, query: str, subject: str, *,
                       config: RetrievalConfig | None = None,
                       query_embedding: list[float] | None = None) -> list[RetrievedChunk]:
        cfg = config or RetrievalConfig()
        chunks: list[RetrievedChunk] = []

        # 向量检索
        if self._vector and query_embedding:
            results = await self._vector(query_embedding, subject, cfg.top_k)
            for c in results:
                c.source = "vector"
            chunks.extend(results)

        # 关键词检索（去重）
        if cfg.enable_keyword and self._keyword:
            seen = {c.chunk_id for c in chunks}
            for c in await self._keyword(query, subject, cfg.top_k):
                if c.chunk_id not in seen:
                    c.source = "keyword"
                    chunks.append(c)

        # 过滤 + rerank
        chunks = [c for c in chunks if c.score >= cfg.similarity_threshold]
        if cfg.enable_rerank and self._rerank:
            chunks = await self._rerank(query, chunks)

        chunks.sort(key=lambda c: c.score, reverse=True)
        result = chunks[:cfg.top_k]
        logger.info("retrieval_done", subject=subject, returned=len(result))
        return result
