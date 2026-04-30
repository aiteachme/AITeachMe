from __future__ import annotations

import pytest

from app.shared.infra.search import api as search_api
from app.shared.infra.search.knowledge import RetrievedChunk
from app.workflows.interact.chat.lib import retrieval


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
