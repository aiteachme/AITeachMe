from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

from app.shared.infra.traced_execution import TracedExecutionContext, TracedExecutionResult
from app.shared.infra.search import ContextCompressor
from app.shared.infra.search.types import ScrapedPage, SearchResult
from app.shared.infra.tools.builtin.web_scraping import scrape_urls
from app.workflows.common.context import create_langgraph_dev_context
from app.workflows.digest.docgen.runtime import DocGenResearchRuntime
from app.workflows.digest.docgen.runtime.query_planning import ResearchSubQueryPlan, generate_sub_queries
from app.workflows.digest.docgen.graph import build_resolve_titles_node, build_targeted_research_node


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


async def _fake_query_planner(*_args, **_kwargs) -> ResearchSubQueryPlan:
    return ResearchSubQueryPlan(
        queries=[
            "partial derivative intuitive definition",
            "partial derivative geometric meaning example",
            "partial derivative geometric meaning example",
        ]
    )


async def _run_context_manager_fast_path() -> TracedExecutionResult:
    manager = ContextCompressor(TracedExecutionContext(subject="demo"))
    return await manager.run(
        query="partial derivative geometric meaning",
        documents=[
            "# Partial Derivative\n\nPartial derivatives describe the rate of change along one coordinate direction.",
            "# Example\n\nA surface slice helps explain the geometric meaning more directly.",
        ],
        max_results=2,
    )


def test_context_manager_fast_path_keeps_small_documents() -> None:
    result = asyncio.run(_run_context_manager_fast_path())

    assert result.metadata["compression_mode"] == "fast_path"
    assert "Partial Derivative" in result.content
    assert "Example" in result.content


def test_context_manager_embedding_filter_prefers_relevant_passages() -> None:
    relevant_doc = "# Partial Derivative\n\n" + ("partial derivative gradient directional derivative surface slice " * 120)
    irrelevant_doc = "# Probability\n\n" + ("random variable probability distribution bayes theorem " * 120)

    async def fake_embed_texts(texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for text in texts:
            if "partial derivative" in text or "gradient" in text or "surface slice" in text:
                embeddings.append([1.0, 0.0])
            else:
                embeddings.append([0.0, 1.0])
        return embeddings

    manager = ContextCompressor(TracedExecutionContext(subject="demo"))
    with patch("app.shared.infra.search.context_compression.aembed_texts", new=fake_embed_texts):
        result = asyncio.run(
            manager.run(
                query="partial derivative",
                focus_terms=["gradient", "surface slice"],
                documents=[relevant_doc, irrelevant_doc],
                max_results=2,
            )
        )

    assert result.metadata["compression_mode"] == "embedding_filter"
    assert "partial derivative" in result.content
    assert "probability distribution" not in result.content


def test_generate_sub_queries_prefers_structured_result_and_dedupes() -> None:
    result = asyncio.run(
        generate_sub_queries(
            "partial derivative",
            context=["geometric meaning", "worked examples"],
            max_queries=3,
            llm_caller=_fake_query_planner,
        )
    )

    assert result == [
        "partial derivative intuitive definition",
        "partial derivative geometric meaning example",
    ]


def test_scrape_urls_dedupes_and_keeps_url_order() -> None:
    html_scraper = FakeScraper(
        {
            "https://example.com/a": ScrapedPage(url="https://example.com/a", title="A", content="Alpha", success=True),
            "https://example.com/b": ScrapedPage(url="https://example.com/b", title="B", content="Beta", success=True),
        }
    )

    with patch(
        "app.shared.infra.tools.builtin.web_scraping.get_scraper_for_url",
        new=lambda _url: html_scraper,
    ):
        pages = asyncio.run(
            scrape_urls(
                [
                    "https://example.com/a",
                    "https://example.com/a",
                    "https://example.com/b",
                ],
                max_workers=2,
            )
        )

    assert [page.url for page in pages] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert html_scraper.calls == [
        "https://example.com/a",
        "https://example.com/b",
    ]


def test_research_conductor_skips_web_when_local_results_are_enough() -> None:
    local_results = [
        SearchResult(url="local://chunk/1", title="Partial derivative definition", snippet="Rate of change on one axis", source="local_rag"),
        SearchResult(url="local://chunk/2", title="Geometric meaning", snippet="Surface slice interpretation", source="local_rag"),
    ]
    local_retriever = FakeRetriever(name="local_rag", results=local_results)
    web_retriever = FakeRetriever(
        name="duckduckgo",
        results=[SearchResult(url="https://example.com", title="web", snippet="web snippet", source="duckduckgo")],
    )

    skill = DocGenResearchRuntime(TracedExecutionContext(subject="demo"))

    async def no_sub_queries(*_args, **_kwargs) -> list[str]:
        return []

    with patch("app.workflows.digest.docgen.runtime.research.LocalRAGRetriever", new=lambda **_kwargs: local_retriever), patch(
        "app.workflows.digest.docgen.runtime.research.get_retrievers_for_subject",
        new=lambda **_kwargs: [local_retriever, web_retriever],
    ), patch(
        "app.workflows.digest.docgen.runtime.research.generate_sub_queries",
        new=no_sub_queries,
    ):
        result = asyncio.run(
            skill.run(
                queries=["partial derivative geometric meaning"],
                local_rag_subject="demo",
            )
        )

    assert result.metadata["local_hits"] == 2
    assert result.metadata["web_hits"] == 0
    assert result.metadata["fallback_used"] is False
    assert result.metadata["executed_queries"] == ["partial derivative geometric meaning"]
    assert result.metadata["research_round_count"] == 1
    assert result.metadata["coverage_score"] == 1.0
    assert result.metadata["retriever_stats"]["local_rag"]["query_count"] == 1
    assert result.metadata["retriever_stats"]["local_rag"]["result_count"] == 2
    assert web_retriever.calls == []
    assert "Partial derivative" in result.content


def test_research_conductor_applies_retrieval_profile_to_factory() -> None:
    local_retriever = FakeRetriever(
        name="local_rag",
        results=[
            SearchResult(url="local://chunk/1", title="Partial derivative definition", snippet="Rate of change", source="local_rag")
        ],
    )
    web_retriever = FakeRetriever(
        name="semantic_scholar",
        results=[SearchResult(url="https://example.com/paper", title="paper", snippet="paper snippet", source="semantic_scholar")],
    )
    captured: dict[str, object] = {}
    skill = DocGenResearchRuntime(TracedExecutionContext(subject="demo", retrieval_profile="docgen_systematic"))

    async def no_sub_queries(*_args, **_kwargs) -> list[str]:
        return []

    def fake_get_retrievers_for_subject(**kwargs):
        captured.update(kwargs)
        return [local_retriever, web_retriever]

    with patch("app.workflows.digest.docgen.runtime.research.LocalRAGRetriever", new=lambda **_kwargs: local_retriever), patch(
        "app.workflows.digest.docgen.runtime.research.get_retrievers_for_subject",
        new=fake_get_retrievers_for_subject,
    ), patch(
        "app.workflows.digest.docgen.runtime.research.get_configured_retriever_names",
        new=lambda **_kwargs: ["local_rag", "tavily", "arxiv", "semantic_scholar"],
    ), patch(
        "app.workflows.digest.docgen.runtime.research.generate_sub_queries",
        new=no_sub_queries,
    ):
        result = asyncio.run(
            skill.run(
                queries=["partial derivative history"],
                local_rag_subject="demo",
                retrieval_profile="docgen_systematic",
            )
        )

    assert captured["profile"] == "docgen_systematic"
    assert result.metadata["requested_retrieval_profile"] == "docgen_systematic"
    assert result.metadata["applied_retrieval_profile"] == "docgen_systematic"
    assert result.metadata["configured_retrievers"] == ["local_rag", "tavily", "arxiv", "semantic_scholar"]
    assert result.metadata["active_retrievers"] == ["local_rag", "semantic_scholar"]


def test_research_conductor_falls_back_to_web_scraping_and_purifies() -> None:
    local_retriever = FakeRetriever(
        name="local_rag",
        results=[SearchResult(url="local://chunk/1", title="Definition", snippet="Rate of change along one axis", source="local_rag")],
    )
    web_retriever = FakeRetriever(
        name="duckduckgo",
        results=[
            SearchResult(url="https://example.com/math", title="Geometric meaning", snippet="surface slice and tangent slope", source="duckduckgo"),
            SearchResult(url="https://example.com/math", title="Geometric meaning", snippet="duplicate result", source="duckduckgo"),
            SearchResult(url="https://example.com/proof", title="Worked example", snippet="example and solution", source="duckduckgo"),
        ],
    )
    scraper = FakeScraper(
        {
            "https://example.com/math": ScrapedPage(
                url="https://example.com/math",
                title="Geometric meaning of partial derivatives",
                content="A surface slice helps explain the relation between tangent slope and partial derivative.",
                success=True,
            ),
            "https://example.com/proof": ScrapedPage(
                url="https://example.com/proof",
                success=False,
                error="network",
            ),
        }
    )
    skill = DocGenResearchRuntime(TracedExecutionContext(subject="demo", llm_caller=_fake_llm_caller))

    async def no_sub_queries(*_args, **_kwargs) -> list[str]:
        return []

    async def fake_scrape_urls(urls: list[str], *, max_workers: int | None = None) -> list[ScrapedPage]:
        del max_workers
        return [scraper.pages[url] for url in urls]

    with patch("app.workflows.digest.docgen.runtime.research.LocalRAGRetriever", new=lambda **_kwargs: local_retriever), patch(
        "app.workflows.digest.docgen.runtime.research.get_retrievers_for_subject",
        new=lambda **_kwargs: [local_retriever, web_retriever],
    ), patch(
        "app.workflows.digest.docgen.runtime.research.generate_sub_queries",
        new=no_sub_queries,
    ), patch(
        "app.workflows.digest.docgen.runtime.research.scrape_urls",
        new=fake_scrape_urls,
    ):
        result = asyncio.run(
            skill.run(
                queries=["partial derivative geometric meaning"],
                local_rag_subject="demo",
                chapter_title="Geometric meaning of partial derivatives",
                objective="Help the learner connect surface slices, tangent slopes, and partial derivatives.",
                required_elements=["geometric meaning", "surface slice", "worked example"],
                digest_mode="systematic",
            )
        )

    assert result.content == "Purified research notes"
    assert result.metadata["fallback_used"] is True
    assert result.metadata["purify_used"] is True
    assert result.metadata["scraped_url_count"] == 1
    assert result.metadata["executed_queries"][0] == "partial derivative geometric meaning"
    assert result.metadata["research_round_count"] >= 1
    assert result.metadata["retriever_stats"]["local_rag"]["query_count"] >= 1
    assert result.metadata["retriever_stats"]["duckduckgo"]["query_count"] >= 1
    assert result.metadata["trusted_source_count"] >= 1
    assert result.metadata["web_source_count"] >= 1
    assert "source_class_breakdown" in result.metadata
    assert sorted(result.sources) == ["https://example.com/math", "https://example.com/proof", "local://chunk/1"]


def test_research_conductor_enqueues_gap_queries_when_required_elements_are_missing() -> None:
    local_retriever = FakeRetriever(
        name="local_rag",
        results=[
            SearchResult(
                url="local://chunk/1",
                title="Definition",
                snippet="Partial derivatives describe local rate of change.",
                source="local_rag",
            )
        ],
    )
    web_retriever = FakeRetriever(
        name="duckduckgo",
        results=[
            SearchResult(
                url="https://example.com/math",
                title="Definition and intuition",
                snippet="surface slice intuition without worked example",
                source="duckduckgo",
            )
        ],
    )
    skill = DocGenResearchRuntime(TracedExecutionContext(subject="demo"))

    async def no_sub_queries(*_args, **_kwargs) -> list[str]:
        return []

    async def fake_scrape_urls(urls: list[str], *, max_workers: int | None = None) -> list[ScrapedPage]:
        del max_workers
        return [
            ScrapedPage(
                url=url,
                title="Definition and intuition",
                content="This page explains the definition and surface slice intuition only.",
                success=True,
            )
            for url in urls
        ]

    with patch("app.workflows.digest.docgen.runtime.research.LocalRAGRetriever", new=lambda **_kwargs: local_retriever), patch(
        "app.workflows.digest.docgen.runtime.research.get_retrievers_for_subject",
        new=lambda **_kwargs: [local_retriever, web_retriever],
    ), patch(
        "app.workflows.digest.docgen.runtime.research.generate_sub_queries",
        new=no_sub_queries,
    ), patch(
        "app.workflows.digest.docgen.runtime.research.scrape_urls",
        new=fake_scrape_urls,
    ):
        result = asyncio.run(
            skill.run(
                queries=["partial derivative geometric meaning"],
                local_rag_subject="demo",
                chapter_title="Geometric meaning of partial derivatives",
                objective="Connect surface slices and worked examples.",
                required_elements=["surface slice", "worked example"],
                digest_mode="systematic",
            )
        )

    assert result.metadata["research_round_count"] >= 2
    assert result.metadata["executed_queries"][0] == "partial derivative geometric meaning"
    assert any("worked example" in query.lower() for query in result.metadata["executed_queries"][1:])
    assert "worked example" in " ".join(result.metadata["gaps_remaining"]).lower()


def test_targeted_research_node_passes_chapter_focus_into_skill() -> None:
    captured: dict[str, object] = {}

    class FakeResearchConductor:
        def __init__(self, context) -> None:
            captured["context"] = context

        async def run(self, **kwargs):
            captured["kwargs"] = kwargs
            return TracedExecutionResult(
                content="Dense research context",
                sources=["https://example.com/math"],
                metadata={
                    "local_hits": 2,
                    "web_hits": 1,
                    "fallback_used": True,
                    "compression_mode": "embedding_filter",
                    "purify_used": True,
                    "requested_retrieval_profile": "docgen_sprint",
                    "applied_retrieval_profile": "docgen_sprint",
                    "configured_retrievers": ["local_rag", "tavily", "bocha"],
                    "active_retrievers": ["local_rag", "tavily"],
                    "executed_queries": ["partial derivative geometric meaning"],
                    "curated_source_count": 3,
                    "trusted_source_count": 2,
                    "retriever_stats": {"local_rag": {"query_count": 1, "result_count": 2}},
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
            "title": "第 1 章",
            "objective": "Help the learner understand the link between surface slices and partial derivatives.",
            "required_elements": ["geometric meaning", "surface slice"],
            "search_queries": ["partial derivative geometric meaning"],
            "source_file_ids": [1],
        },
    }

    with patch("app.workflows.digest.docgen.nodes.targeted_research_node.ResearchConductor", new=FakeResearchConductor):
        result = asyncio.run(node(state))

    kwargs = captured["kwargs"]
    context = captured["context"]
    assert kwargs["queries"] == ["partial derivative geometric meaning"]
    assert kwargs["chapter_title"] == "第 1 章"
    assert kwargs["objective"] == "Help the learner understand the link between surface slices and partial derivatives."
    assert kwargs["required_elements"] == ["geometric meaning", "surface slice"]
    assert kwargs["digest_mode"] == "sprint"
    assert kwargs["retrieval_profile"] == "docgen_sprint"
    assert context.course_type == "sprint"
    assert context.retrieval_profile == "docgen_sprint"
    assert context.teaching_action == "chapter_research"
    assert result["chapter_materials"][0]["fallback_used"] is True
    assert result["chapter_materials"][0]["compression_mode"] == "embedding_filter"
    assert result["chapter_materials"][0]["curated_source_count"] == 3
    assert result["chapter_materials"][0]["trusted_source_count"] == 2
    assert result["chapter_materials"][0]["retrieval_profile"] == "docgen_sprint"
    assert result["chapter_materials"][0]["requested_retrieval_profile"] == "docgen_sprint"
    assert result["chapter_materials"][0]["applied_retrieval_profile"] == "docgen_sprint"
    assert result["chapter_materials"][0]["configured_retrievers"] == ["local_rag", "tavily", "bocha"]
    assert result["chapter_materials"][0]["active_retrievers"] == ["local_rag", "tavily"]
    assert result["chapter_materials"][0]["teaching_action"] == "chapter_research"
    assert result["chapter_materials"][0]["retriever_stats"]["local_rag"]["query_count"] == 1
    assert result["llm_calls_total"] == 1


def test_resolve_titles_node_generates_resolved_title_from_research_context() -> None:
    node = build_resolve_titles_node(context=create_langgraph_dev_context("digest.docgen.title_test"))
    state = {
        "subject": "demo",
        "requested_at": datetime.utcnow(),
        "build_session_id": "build-1",
        "planner_session_id": "planner-1",
        "confirmed_plan_id": "plan-1",
        "digest_mode": "systematic",
        "course_type": "systematic",
        "retrieval_profile": "docgen_systematic",
        "chapter_materials": [
            {
                "chapter_index": 1,
                "title": "第 1 章",
                "objective": "帮助学习者先建立偏导数的几何直觉，再连接到定义。",
                "required_elements": ["几何直觉", "偏导数定义", "曲面切片"],
                "search_queries": ["偏导数 几何意义", "偏导数 曲面切片"],
                "writing_instructions": "先讲直观图景，再进入定义和例子。",
                "dense_context": "偏导数可以理解为多元函数在某个坐标方向上的局部变化率。通过曲面切片和切线斜率，学生更容易建立几何直觉。",
                "source_titles": ["MIT OCW Partial Derivatives"],
                "local_hits": 1,
                "web_hits": 1,
                "sources": ["local://chunk/1", "https://example.edu/math"],
            }
        ],
    }

    with patch(
        "app.workflows.digest.docgen.nodes.resolve_titles_node.acompletion_with_fallback",
        new=AsyncMock(return_value="多元函数的变化率直觉"),
    ), patch(
        "app.workflows.digest.docgen.nodes.resolve_titles_node.update_knowledge_build_status",
    ), patch(
        "app.workflows.digest.docgen.nodes.resolve_titles_node.append_knowledge_build_recent_event",
    ), patch(
        "app.workflows.digest.docgen.nodes.resolve_titles_node.upsert_knowledge_build_chapter_progress",
    ):
        result = asyncio.run(node(state))

    assert result["chapter_materials"][0]["resolved_title"] == "多元函数的变化率直觉"


