"""搜索系统对外 API — 外部模块的唯一入口。

提供两个核心函数：
- ``web_search()`` — 搜索互联网
- ``search_knowledge()`` — 搜索知识库（向量 + 关键词 + rerank）
"""

from __future__ import annotations

import structlog

from app.platform.retrievers import RetrievalConfig, RetrievedChunk
from app.platform.search.types import WebSearchResult
from app.platform.search.web import dispatch_web_search

logger = structlog.get_logger()


async def web_search(
    query: str,
    *,
    top_k: int = 5,
) -> list[WebSearchResult]:
    """搜索互联网 — 自动选择可用搜索提供商。

    Args:
        query: 搜索查询（自然语言）。
        top_k: 返回最多几条结果。

    Returns:
        WebSearchResult 列表（title, url, snippet）。
        如果搜索提供商不可用，返回空列表（不抛异常）。

    Example::

        from app.platform.search.api import web_search
        results = await web_search("贝叶斯定理 直觉解释")
        for r in results:
            print(f"{r.title}: {r.url}")
    """

    return await dispatch_web_search(query, top_k=top_k)


async def search_knowledge(
    query: str,
    subject_id: str,
    *,
    top_k: int = 5,
    enable_rerank: bool = True,
) -> list[RetrievedChunk]:
    """搜索知识库 — 自动完成 embedding → 向量检索 → rerank。

    整合现有的 embedding、sqlite-vec 向量检索和 reranker 能力。
    外部只需提供 query 和 subject_id，所有中间步骤内部处理。

    Args:
        query: 搜索查询（自然语言）。
        subject_id: 学科标识。
        top_k: 返回最多几条结果。
        enable_rerank: 是否启用重排序（需要配置 rerank 模型）。

    Returns:
        RetrievedChunk 列表（按相关性排序）。

    Example::

        from app.platform.search.api import search_knowledge
        chunks = await search_knowledge("什么是特征值", subject_id="linear-algebra")
        for c in chunks:
            print(f"[{c.title}] {c.content[:100]}")
    """

    from app.infra.config import get_settings
    from app.platform.embedding import aembed_texts

    settings = get_settings()

    # 1. 向量化查询
    try:
        query_embeddings = await aembed_texts([query])
        query_vec = query_embeddings[0] if query_embeddings else None
    except Exception as exc:
        logger.warning("search_knowledge_embedding_failed", error=str(exc))
        query_vec = None

    # 2. 向量检索
    chunks: list[RetrievedChunk] = []
    if query_vec is not None:
        chunks = await _vector_search(query_vec, subject_id, top_k * 2)

    # 3. Rerank（如果配置了模型）
    if enable_rerank and chunks and settings.rag_rerank_model:
        try:
            from app.platform.reranker import rerank_chunks
            chunks = await rerank_chunks(query, chunks, top_k=top_k)
        except Exception as exc:
            logger.warning("search_knowledge_rerank_failed", error=str(exc))

    # 4. 返回
    result = chunks[:top_k]
    logger.info("knowledge_search_complete",
                subject=subject_id,
                query_len=len(query),
                result_count=len(result))
    return result


async def _vector_search(
    query_embedding: list[float],
    subject_id: str,
    top_k: int,
) -> list[RetrievedChunk]:
    """基于 sqlite-vec 的向量检索。"""

    from app.infra.database import is_vec_ready

    if not is_vec_ready():
        logger.warning("vector_search_skipped", reason="sqlite-vec 不可用")
        return []

    try:
        from app.infra.database import get_engine
        import sqlalchemy as sa

        engine = get_engine()
        with engine.connect() as conn:
            # 使用 sqlite-vec 的 vec_distance_cosine 函数
            rows = conn.execute(
                sa.text("""
                    SELECT
                        c.id, c.source_id, c.content,
                        c.chunk_role, c.chunk_index,
                        vec_distance_cosine(e.embedding, :query_vec) as distance
                    FROM chunk_embeddings e
                    JOIN retrieval_chunk c ON e.chunk_id = c.id
                    WHERE c.subject_id = :subject_id
                    ORDER BY distance ASC
                    LIMIT :top_k
                """),
                {
                    "query_vec": _serialize_vec(query_embedding),
                    "subject_id": subject_id,
                    "top_k": top_k,
                },
            ).fetchall()

            return [
                RetrievedChunk(
                    chunk_id=row[0],
                    document_id=row[1],
                    title=row[3] or "",
                    header_path="",
                    content=row[2],
                    score=1.0 - float(row[5]),  # cosine distance → similarity
                    source="vector",
                )
                for row in rows
            ]
    except Exception as exc:
        logger.warning("vector_search_failed", error=str(exc))
        return []


def _serialize_vec(embedding: list[float]) -> bytes:
    """将 embedding 序列化为 sqlite-vec 需要的二进制格式。"""
    import struct
    return struct.pack(f"{len(embedding)}f", *embedding)
