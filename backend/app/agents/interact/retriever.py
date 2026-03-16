"""检索结果整理工具。"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.embedding import aembed_texts


@dataclass
class RetrievalResult:
    """用于聊天提示词的检索结果。"""

    chunk_id: int
    document_id: int
    title: str
    header_path: str
    content: str
    score: float
    low_relevance: bool


def build_retrieval_results(
    *,
    items: list[dict],
    similarity_threshold: float,
) -> list[RetrievalResult]:
    """把仓储层结果转换为聊天检索结果。"""

    results: list[RetrievalResult] = []
    for item in items:
        results.append(
            RetrievalResult(
                chunk_id=item["chunk_id"],
                document_id=item["document_id"],
                title=item["title"],
                header_path=item["header_path"],
                content=item["content"],
                score=item["score"],
                low_relevance=item["score"] < similarity_threshold,
            )
        )
    return results


async def build_query_embedding(query: str) -> list[float]:
    """为用户问题生成查询向量。"""

    return (await aembed_texts([query]))[0]


async def retrieve(
    *,
    query: str,
    subject: str,
    top_k: int,
    similarity_threshold: float,
    search_func,
) -> list[RetrievalResult]:
    """执行一次检索流程。"""

    query_embedding = await build_query_embedding(query)
    items = search_func(query_embedding, subject, top_k)
    return build_retrieval_results(items=items, similarity_threshold=similarity_threshold)
