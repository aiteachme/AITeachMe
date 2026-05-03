from __future__ import annotations

import pytest

from app.shared.infra.search import api as search_api
from app.shared.infra.search.knowledge import RetrievedChunk
from app.workflows.interact.chat.lib import retrieval
from app.workflows.interact.chat.lib.types import RetrievedContext


@pytest.mark.anyio
async def test_interact_vector_fallback_uses_public_knowledge_search(monkeypatch) -> None:
    async def fake_search_knowledge(
        query: str,
        course_id: str,
        *,
        top_k: int,
        enable_rerank: bool,
    ) -> list[RetrievedChunk]:
        assert query == "拉格朗日乘子"
        assert course_id == "course_math"
        assert top_k == 3
        assert enable_rerank is True
        return [
            RetrievedChunk(
                chunk_id=11,
                file_id="file_1",
                title="约束优化",
                header_path="多元函数 > 约束优化",
                content="拉格朗日乘子法用于处理等式约束下的极值问题。",
                score=0.81,
                source="llamaindex+rerank",
            )
        ]

    monkeypatch.setattr(search_api, "search_knowledge", fake_search_knowledge)

    results = await retrieval._retrieve_vector_context(
        session=None,  # type: ignore[arg-type]
        query="拉格朗日乘子",
        course_id="course_math",
        top_k=3,
        similarity_threshold=0.3,
    )

    assert len(results) == 1
    assert results[0].chunk_id == 11
    assert results[0].retrieval_source == "vector"


def test_merge_context_results_keeps_vector_hits_before_weak_graph_hits() -> None:
    graph_results = [
        RetrievedContext(
            chunk_id=100 + index,
            file_id=f"graph_{index}",
            title=f"弱图谱 {index}",
            header_path=f"弱图谱 {index}",
            content="低相关图谱上下文",
            score=0.1,
            low_relevance=True,
            knowledge_unit_id=1000 + index,
            retrieval_source="knowledge_unit",
        )
        for index in range(3)
    ]
    vector_results = [
        RetrievedContext(
            chunk_id=200,
            file_id="vector_1",
            title="强向量命中",
            header_path="强向量命中",
            content="更相关的向量上下文",
            score=0.82,
            low_relevance=False,
            retrieval_source="vector",
        )
    ]

    results = retrieval._merge_context_results(graph_results, vector_results, top_k=3)

    assert [item.retrieval_source for item in results] == ["vector", "knowledge_unit", "knowledge_unit"]
    assert results[0].chunk_id == 200
