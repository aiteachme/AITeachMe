"""
向量相似度搜索 — Interact 引擎检索层

查询 chunk_embeddings，支持学科过滤，返回 top-k 块并按相似度降序排列。
检查相似度阈值（默认 0.3），标记低相关性结果。
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from sqlmodel import Session

from app.core.config import get_settings
from app.core.embedding import aembed_texts
from app.repositories.knowledge_repo import ChunkSearchResult, vector_search

logger = structlog.get_logger()


@dataclass
class RetrievalResult:
    """检索结果，包含 chunk 信息、相似度分数和相关性标记。"""
    chunk_id: int
    knowledge_id: int
    title: str
    header_path: str
    content: str
    score: float
    low_relevance: bool  # True 表示低于相似度阈值


async def retrieve(
    session: Session,
    query: str,
    subject: str,
    *,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
) -> list[RetrievalResult]:
    """
    对用户查询进行向量检索，返回按相似度降序排列的结果。

    Args:
        session: 数据库会话
        query: 用户查询文本
        subject: 学科标识
        top_k: 返回的最大结果数（默认从 settings.rag_top_k 读取）
        similarity_threshold: 相似度阈值（默认从 settings.rag_similarity_threshold 读取）

    Returns:
        按相似度降序排列的 RetrievalResult 列表
    """
    settings = get_settings()
    top_k = top_k or settings.rag_top_k
    similarity_threshold = similarity_threshold if similarity_threshold is not None else settings.rag_similarity_threshold

    # 计算查询向量
    embeddings = await aembed_texts([query])
    query_embedding = embeddings[0]

    # 向量搜索
    search_results: list[ChunkSearchResult] = vector_search(
        session, query_embedding, subject, top_k=top_k
    )

    results: list[RetrievalResult] = []
    for sr in search_results:
        chunk = sr.chunk
        results.append(RetrievalResult(
            chunk_id=chunk.id,  # type: ignore[arg-type]
            knowledge_id=chunk.knowledge_id,
            title=chunk.title,
            header_path=chunk.header_path,
            content=chunk.content,
            score=sr.score,
            low_relevance=sr.score < similarity_threshold,
        ))

    all_low = all(r.low_relevance for r in results) if results else True
    logger.info(
        "retrieval_complete",
        subject=subject,
        query_len=len(query),
        num_results=len(results),
        all_low_relevance=all_low,
    )

    return results
