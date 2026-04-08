from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import patch

from app.shared.infra.search.types import ScrapedPage, SearchResult
from app.shared.infra.skills import ContextManager, ResearchConductor, SkillContext, SkillResult
from app.workflows.common.context import create_langgraph_dev_context
from app.workflows.digest.docgen.graph import build_targeted_research_node


class FakeRetriever:
    def __init__(self, *, name: str, results: list[SearchResult]) -> None:
        self.name = name
        self.results = results
        self.calls: list[str] = []

    async def traced_search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.calls.append(query)
        return list(self.results[:max_results])


class FakeScraper:
    def __init__(self, pages: dict[str, ScrapedPage]) -> None:
        self.pages = pages
        self.calls: list[str] = []

    async def traced_scrape(self, url: str) -> ScrapedPage:
        self.calls.append(url)
        return self.pages[url]


async def _fake_llm_caller(*_args, **_kwargs) -> str:
    return "Purified research notes"


async def _run_context_manager_fast_path() -> SkillResult:
    manager = ContextManager(SkillContext(subject="demo"))
    return await manager.run(
        query="偏导数 几何意义",
        documents=[
            "# 偏导数\n\n偏导数描述多元函数沿某一坐标方向的变化率。",
            "# 例题\n\n结合曲面截面图可以更直观地理解几何意义。",
        ],
        max_results=2,
    )



def test_context_manager_fast_path_keeps_small_documents() -> None:
    result = asyncio.run(_run_context_manager_fast_path())

    assert result.metadata["compression_mode"] == "fast_path"
    assert "偏导数" in result.content
    assert "例题" in result.content



def test_context_manager_embedding_filter_prefers_relevant_passages() -> None:
    relevant_doc = "# 偏导数\n\n" + ("偏导数 梯度 方向导数 截面图 几何意义 " * 120)
    irrelevant_doc = "# 概率论\n\n" + ("随机变量 概率分布 条件概率 贝叶斯公式 " * 120)

    async def fake_embed_texts(texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for text in texts:
            if "偏导数" in text or "梯度" in text or "几何意义" in text:
                embeddings.append([1.0, 0.0])
            else:
                embeddings.append([0.0, 1.0])
        return embeddings

    manager = ContextManager(SkillContext(subject="demo"))
    with patch("app.shared.infra.skills.context_manager.aembed_texts", new=fake_embed_texts):
        result = asyncio.run(
            manager.run(
                query="偏导数",
                focus_terms=["梯度", "几何意义"],
                documents=[relevant_doc, irrelevant_doc],
                max_results=2,
            )
        )

    assert result.metadata["compression_mode"] == "embedding_filter"
    assert "偏导数" in result.content
    assert "概率分布" not in result.content



def test_research_conductor_skips_web_when_local_results_are_enough() -> None:
    local_results = [
        SearchResult(url="local://chunk/1", title="偏导数定义", snippet="偏导数描述变化率", source="local_rag"),
        SearchResult(url="local://chunk/2", title="几何意义", snippet="曲面截面图帮助理解", source="local_rag"),
    ]
    local_retriever = FakeRetriever(name="local_rag", results=local_results)
    web_retriever = FakeRetriever(
        name="duckduckgo",
        results=[SearchResult(url="https://example.com", title="web", snippet="web snippet", source="duckduckgo")],
    )

    skill = ResearchConductor(SkillContext(subject="demo"))
    with patch("app.shared.infra.skills.researcher.LocalRAGRetriever", new=lambda **_kwargs: local_retriever), patch(
        "app.shared.infra.skills.researcher.get_retrievers_for_subject",
        new=lambda **_kwargs: [local_retriever, web_retriever],
    ):
        result = asyncio.run(
            skill.run(
                queries=["偏导数 几何意义"],
                local_rag_subject="demo",
            )
        )

    assert result.metadata["local_hits"] == 2
    assert result.metadata["web_hits"] == 0
    assert result.metadata["fallback_used"] is False
    assert web_retriever.calls == []
    assert "偏导数" in result.content



def test_research_conductor_falls_back_to_web_scraping_and_purifies() -> None:
    local_retriever = FakeRetriever(
        name="local_rag",
        results=[SearchResult(url="local://chunk/1", title="偏导数定义", snippet="多元函数某方向的变化率", source="local_rag")],
    )
    web_retriever = FakeRetriever(
        name="duckduckgo",
        results=[
            SearchResult(url="https://example.com/math", title="偏导数几何意义", snippet="截面图与切线斜率", source="duckduckgo"),
            SearchResult(url="https://example.com/math", title="偏导数几何意义", snippet="重复结果", source="duckduckgo"),
            SearchResult(url="https://example.com/proof", title="偏导数例题", snippet="例题与解析", source="duckduckgo"),
        ],
    )
    scraper = FakeScraper(
        {
            "https://example.com/math": ScrapedPage(
                url="https://example.com/math",
                title="偏导数的几何意义",
                content="曲面截面图可以帮助理解偏导数与切线斜率的关系。",
                success=True,
            ),
            "https://example.com/proof": ScrapedPage(
                url="https://example.com/proof",
                success=False,
                error="network",
            ),
        }
    )
    skill = ResearchConductor(SkillContext(subject="demo", llm_caller=_fake_llm_caller))

    with patch("app.shared.infra.skills.researcher.LocalRAGRetriever", new=lambda **_kwargs: local_retriever), patch(
        "app.shared.infra.skills.researcher.get_retrievers_for_subject",
        new=lambda **_kwargs: [local_retriever, web_retriever],
    ), patch(
        "app.shared.infra.skills.researcher.get_scraper_for_url",
        new=lambda _url: scraper,
    ):
        result = asyncio.run(
            skill.run(
                queries=["偏导数 几何意义"],
                local_rag_subject="demo",
                chapter_title="偏导数的几何意义",
                objective="帮助学生理解截面图、切线斜率与偏导数之间的关系。",
                required_elements=["几何意义", "截面图", "例题"],
                digest_mode="systematic",
            )
        )

    assert result.content == "Purified research notes"
    assert result.metadata["fallback_used"] is True
    assert result.metadata["purify_used"] is True
    assert result.metadata["scraped_url_count"] == 1
    assert scraper.calls == ["https://example.com/math", "https://example.com/proof"]
    assert sorted(result.sources) == ["https://example.com/math", "https://example.com/proof", "local://chunk/1"]



def test_targeted_research_node_passes_chapter_focus_into_skill() -> None:
    captured: dict[str, object] = {}

    class FakeResearchConductor:
        def __init__(self, context) -> None:
            captured["context"] = context

        async def run(self, **kwargs):
            captured["kwargs"] = kwargs
            return SkillResult(
                content="Dense research context",
                sources=["https://example.com/math"],
                metadata={
                    "local_hits": 2,
                    "web_hits": 1,
                    "fallback_used": True,
                    "compression_mode": "embedding_filter",
                    "purify_used": True,
                    "executed_queries": ["偏导数 几何意义"],
                },
            )

    node = build_targeted_research_node(context=create_langgraph_dev_context("digest.docgen.test"))
    state = {
        "subject": "demo",
        "requested_at": datetime.utcnow(),
        "build_session_id": "build-1",
        "planner_session_id": "planner-1",
        "confirmed_plan_id": "plan-1",
        "digest_mode": "sprint",
        "shared_inputs": None,
        "chapter_assignment": {
            "chapter_index": 1,
            "title": "偏导数的几何意义",
            "objective": "帮助学生看懂偏导数与截面图的关系。",
            "required_elements": ["几何意义", "截面图"],
            "search_queries": ["偏导数 几何意义"],
            "source_file_ids": [1],
        },
    }

    with patch("app.workflows.digest.docgen.graph.ResearchConductor", new=FakeResearchConductor):
        result = asyncio.run(node(state))

    kwargs = captured["kwargs"]
    assert kwargs["chapter_title"] == "偏导数的几何意义"
    assert kwargs["objective"] == "帮助学生看懂偏导数与截面图的关系。"
    assert kwargs["required_elements"] == ["几何意义", "截面图"]
    assert kwargs["digest_mode"] == "sprint"
    assert result["chapter_materials"][0]["fallback_used"] is True
    assert result["chapter_materials"][0]["compression_mode"] == "embedding_filter"
    assert result["llm_calls_total"] == 1
