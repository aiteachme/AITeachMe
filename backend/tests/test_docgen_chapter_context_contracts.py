from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.search.retrievers.local_rag import LocalRAGRetriever
from app.shared.infra.search.source_curation import SourceCurator
from app.shared.infra.search.types import ScrapedPage, SearchResult
from app.workflows.digest.common.models import DigestMaterialContext, SectionPacket, SourcePacket
from app.workflows.digest.docgen.lib import chapter_context as chapter_context_module
from app.workflows.digest.docgen.lib.chapter_context import DocGenChapterContextRuntime
from app.workflows.digest.docgen.lib.query_planning import enrich_queries_for_education, enrich_queries_for_retriever
from app.workflows.digest.docgen.lib.source_slices import build_priority_source_context, build_section_catalog_for_file


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _fake_llm(*_args, **_kwargs) -> str:
    return "purified context"


def _runtime() -> DocGenChapterContextRuntime:
    return DocGenChapterContextRuntime(
        TracedExecutionContext(
            course_id="course_docgen0000",
            build_session_id="build-1",
            digest_mode="systematic",
            llm_caller=_fake_llm,
        )
    )


def _result(url: str, title: str, snippet: str, *, score: float = 0.8, source: str = "web") -> SearchResult:
    return SearchResult(url=url, title=title, snippet=snippet, score=score, source=source)


def test_source_filtering_coverage_and_gap_query_helpers() -> None:
    runtime = _runtime()
    results = [
        _result("local://section/1", "Local matrix", "矩阵乘法和秩", source="local_rag"),
        _result("https://example.org/math/matrix", "External org", "矩阵基础"),
        _result("https://baidu.com/zhidao/question", "Low value", "低质量问答"),
        _result("https://ocw.mit.edu/matrix", "MIT OCW", "linear algebra matrix rank"),
        _result("https://math.stackexchange.com/q/1", "Community", "rank intuition"),
        _result("", "No URL", "fallback snippet"),
    ]

    candidates = list(results)
    deduped = runtime._dedupe_results([results[0], results[0], results[-1]], max_results=3)
    stats: dict[str, dict[str, object]] = {}
    runtime._record_retriever_call(stats, retriever_name="local_rag", query="矩阵", results=[results[0]])
    runtime._record_retriever_call(stats, retriever_name="local_rag", query="矩阵", results=[])
    pending = ["矩阵", "秩", "线性映射"]
    round_queries = runtime._take_round_queries(pending, executed_queries=["矩阵"], limit=2)
    enqueued = runtime._enqueue_gap_queries(pending, ["秩", "特征值", " "], limit=5)
    assessment = runtime._assess_coverage(
        dense_context="矩阵乘法说明了秩的直觉，也包含线性映射例子。",
        objective="掌握矩阵 线性映射",
        required_elements=["矩阵乘法", "特征值应用"],
        digest_mode="systematic",
        curated_results=candidates,
    )
    gap_queries = runtime._build_gap_queries(
        chapter_title="矩阵基础",
        objective="掌握矩阵 线性映射",
        gaps=assessment["gaps_remaining"],
        digest_mode="systematic",
        max_queries=2,
    )
    breakdown = runtime._classify_source_breakdown(candidates)

    assert [item.url for item in candidates] == [
        "local://section/1",
        "https://example.org/math/matrix",
        "https://baidu.com/zhidao/question",
        "https://ocw.mit.edu/matrix",
        "https://math.stackexchange.com/q/1",
        "",
    ]
    assert [item.title for item in deduped] == ["Local matrix", "No URL"]
    assert stats["local_rag"]["query_count"] == 2
    assert stats["local_rag"]["result_count"] == 1
    assert round_queries == ["秩", "线性映射"]
    assert enqueued == ["特征值"]
    assert assessment["coverage_score"] < 1
    assert "特征值应用" in assessment["gaps_remaining"]
    assert gap_queries and all(query.startswith("矩阵基础") for query in gap_queries)
    assert breakdown == {"local": 1, "institutional": 1, "academic": 1, "general_web": 3}


def test_dedupe_results_ranks_local_and_reliable_sources_before_truncation() -> None:
    runtime = _runtime()
    results = [
        _result("https://random.example.com/a", "Random", "泛泛摘要" * 20, score=0.95),
        _result("https://arxiv.org/abs/1234", "Paper", "矩阵分解 低秩近似 论文", score=0.6),
        _result("local://section/1", "Local", "本地矩阵分解材料", score=0.2, source="local_rag"),
    ]

    deduped = runtime._dedupe_results(results, max_results=2)

    assert [item.url for item in deduped] == ["local://section/1", "https://arxiv.org/abs/1234"]


@pytest.mark.anyio
async def test_source_curator_demotes_noisy_sources_instead_of_hard_filtering() -> None:
    curator = SourceCurator(_runtime().context)

    curated, metadata = await curator.curate_sources(
        query="矩阵分解",
        sources=[
            _result("https://zhihu.com/question/1", "矩阵分解经验", "矩阵分解的直觉解释和例题", score=0.95),
            _result("https://baidu.com/zhidao/question", "矩阵分解问答", "矩阵分解的基础问答", score=0.9),
            _result("https://ocw.mit.edu/matrix", "MIT Matrix", "矩阵分解 matrix factorization lecture notes", score=0.6),
        ],
        max_results=3,
    )

    urls = [item.url for item in curated]
    assert "https://zhihu.com/question/1" in urls
    assert "https://baidu.com/zhidao/question" in urls
    assert urls.index("https://ocw.mit.edu/matrix") < urls.index("https://baidu.com/zhidao/question")
    assert metadata["filtered_count"] == 3


def test_education_query_enrichment_avoids_filtered_low_value_sites() -> None:
    broad_queries = enrich_queries_for_education(["矩阵分解"], domain="zh", max_site_filters_per_query=3)
    wiki_queries = enrich_queries_for_retriever(
        ["矩阵分解"],
        domain="zh",
        retriever_name="zh_wikipedia",
    )
    web_queries = enrich_queries_for_retriever(
        ["矩阵分解"],
        domain="zh",
        retriever_name="tavily",
        max_site_filters_per_query=2,
    )
    explicit_university_queries = enrich_queries_for_retriever(
        ["矩阵分解"],
        domain="university",
        retriever_name="tavily",
        max_site_filters_per_query=1,
    )

    assert all("zhihu.com" not in query and "csdn.net" not in query for query in broad_queries)
    assert broad_queries == ["矩阵分解"]
    assert wiki_queries == ["矩阵分解"]
    assert web_queries == ["矩阵分解"]
    assert explicit_university_queries == ["矩阵分解", "矩阵分解 site:icourse163.org"]


def test_external_retrievers_are_balanced_across_source_types() -> None:
    runtime = _runtime()
    retrievers = [
        SimpleNamespace(name="zh_wikibooks"),
        SimpleNamespace(name="zh_wikiversity"),
        SimpleNamespace(name="zh_wikipedia"),
        SimpleNamespace(name="searxng"),
        SimpleNamespace(name="tavily"),
        SimpleNamespace(name="arxiv"),
        SimpleNamespace(name="semantic_scholar"),
    ]

    balanced = runtime._balance_external_retrievers(retrievers)

    assert [item.name for item in balanced[:6]] == [
        "searxng",
        "arxiv",
        "zh_wikibooks",
        "tavily",
        "semantic_scholar",
        "zh_wikiversity",
    ]


def test_external_search_jobs_try_provider_original_queries_before_variants() -> None:
    runtime = _runtime()
    retrievers = [
        SimpleNamespace(name="zh_wikibooks"),
        SimpleNamespace(name="tavily"),
        SimpleNamespace(name="arxiv"),
    ]

    jobs = runtime._build_external_search_jobs(
        base_query="矩阵分解",
        retrievers=retrievers,
        search_domain="zh",
        job_limit=3,
    )
    expanded_jobs = runtime._build_external_search_jobs(
        base_query="矩阵分解",
        retrievers=retrievers[:2],
        search_domain="zh",
        job_limit=4,
    )

    assert [(retriever.name, query) for _base, retriever, query in jobs] == [
        ("zh_wikibooks", "矩阵分解"),
        ("tavily", "矩阵分解"),
        ("arxiv", "矩阵分解"),
    ]
    assert not any("site:" in query for _base, _retriever, query in expanded_jobs)
    assert all("site:" not in query for _base, retriever, query in expanded_jobs if retriever.name == "zh_wikibooks")


def test_source_slice_line_spans_advance_for_repeated_sections() -> None:
    repeated = "重复定义\n共享说明"
    source_text = f"{repeated}\n\n{repeated}"
    packet = SourcePacket(
        file_id="file_1",
        filename="notes.md",
        filetype="markdown",
        markdown_path="",
        asset_dir="",
        normalized_content=source_text,
        char_count=len(source_text),
        has_formulas=False,
        has_tables=False,
        has_images=False,
    )
    sections = [
        SectionPacket(
            digest_chunk_uid="sec_1",
            source_file_id="file_1",
            source_filename="notes.md",
            chunk_index=0,
            title="重复片段一",
            header_path="重复片段一",
            level=1,
            normalized_content=repeated,
            preview=repeated,
            char_count=len(repeated),
        ),
        SectionPacket(
            digest_chunk_uid="sec_2",
            source_file_id="file_1",
            source_filename="notes.md",
            chunk_index=1,
            title="重复片段二",
            header_path="重复片段二",
            level=1,
            normalized_content=repeated,
            preview=repeated,
            char_count=len(repeated),
        ),
    ]

    catalog = build_section_catalog_for_file(packet, sections=sections)
    hydrated = build_priority_source_context(
        DigestMaterialContext(source_packets=[packet], section_packets=sections),
        [{"file_id": "file_1", "section_ref": "sec_2", "section_title": "重复片段二"}],
    )

    assert [(item["line_start"], item["line_end"]) for item in catalog] == [(1, 2), (4, 5)]
    assert hydrated.source_details[0]["line_start"] == 4
    assert hydrated.source_details[0]["line_end"] == 5
    assert "L4: 重复定义" in hydrated.text


def test_local_rag_section_fallback_searches_full_section_content() -> None:
    section = {
        "title": "tail coverage",
        "normalized_content": ("prefix content " * 140) + " tail-only-signal",
    }
    retriever = LocalRAGRetriever(local_sections=[section])

    results = retriever._section_fallback("tail-only-signal", max_results=3)

    assert results
    assert results[0].title == "tail coverage"


@pytest.mark.anyio
async def test_collect_documents_uses_cache_and_snippet_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime()
    fetched_urls: list[str] = []

    async def fake_read_urls(urls, **_kwargs):
        fetched_urls.extend(urls)
        return [
            ScrapedPage(url="https://example.edu/page", title="Example EDU", content="完整正文"),
            ScrapedPage(url="https://example.org/empty", title="", content="", success=False),
        ]

    monkeypatch.setattr(chapter_context_module, "read_urls", fake_read_urls)
    page_cache = {
        "https://cached.org/page": ScrapedPage(
            url="https://cached.org/page",
            title="Cached",
            content="缓存正文",
        )
    }
    results = [
        _result("local://chunk/1", "Local", "本地切片正文", source="local_rag"),
        _result("https://zh.wikipedia.org/wiki/Matrix", "Wikipedia", "百科摘要"),
        _result("https://example.edu/page", "External", "外部摘要"),
        _result("https://example.edu/page", "External duplicate", "重复摘要"),
        _result("https://example.org/empty", "Empty", "空页面摘要"),
        _result("https://noise.example.com/empty", "Noise", "短摘要", score=0.2),
        _result("https://cached.org/page", "Cached", "缓存摘要"),
    ]

    documents, read_count = await runtime._collect_documents(results, page_cache=page_cache, read_timeout_s=0.1)
    cached_documents, cached_read_count = await runtime._collect_documents(
        [_result("https://cached.org/page", "Cached", "缓存摘要")],
        page_cache=page_cache,
        read_timeout_s=0.1,
    )

    assert fetched_urls == ["https://example.edu/page", "https://example.org/empty", "https://noise.example.com/empty"]
    assert read_count == 2
    assert any("本地切片正文" in item for item in documents)
    assert any("百科摘要" in item for item in documents)
    assert any("# Example EDU" in item and "完整正文" in item for item in documents)
    assert any("空页面摘要" in item for item in documents)
    assert not any("短摘要" in item for item in documents)
    assert any("缓存正文" in item for item in documents)
    assert cached_read_count == 1
    assert cached_documents == ["# Cached\n\n缓存正文"]


@pytest.mark.anyio
async def test_research_round_tracks_local_fallback_and_external_hits(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime()
    monkeypatch.setattr(chapter_context_module, "enrich_queries_for_retriever", lambda queries, **_kwargs: queries)

    class FakeRetriever:
        def __init__(self, name: str, results: list[SearchResult]) -> None:
            self.name = name
            self.results = results
            self.queries: list[str] = []

        async def traced_search(self, query: str, *, max_results: int) -> list[SearchResult]:
            self.queries.append(query)
            return self.results[:max_results]

    local = FakeRetriever(
        "local_rag",
        [_result("local://weak", "Weak local", "弱本地材料", score=0.1, source="local_rag")],
    )
    external = FakeRetriever(
        "bocha",
        [
            _result("https://example.edu/a", "External A", "外部资料 A", score=0.9, source="bocha"),
            _result("https://example.edu/b", "External B", "外部资料 B", score=0.8, source="bocha"),
        ],
    )
    retriever_stats: dict[str, dict[str, object]] = {}
    all_results: list[SearchResult] = []
    executed_queries: list[str] = []
    fallback_queries: list[str] = []

    round_result = await runtime._run_research_round(
        round_index=1,
        round_queries=["矩阵"],
        search_domain="zh",
        query_limit=2,
        settings=SimpleNamespace(
            rag=SimpleNamespace(similarity_threshold=0.6),
            local_rag=SimpleNamespace(min_results=2),
        ),
        local_retriever=local,
        other_retrievers=[external],
        local_hits_total=0,
        web_hits_total=0,
        fallback_queries_total=fallback_queries,
        executed_queries=executed_queries,
        retriever_stats=retriever_stats,
        all_results=all_results,
        retrieval_started_at=time.monotonic(),
        retrieval_budget_s=3600.0,
        provider_budget_s=1.0,
    )

    assert round_result["local_hits_total"] == 1
    assert round_result["web_hits_total"] == 2
    assert round_result["round_fallback_queries"] == ["矩阵"]
    assert round_result["round_external_queries"] == ["矩阵"]
    assert executed_queries == ["矩阵"]
    assert fallback_queries == ["矩阵"]
    assert retriever_stats["local_rag"]["result_count"] == 1
    assert retriever_stats["bocha"]["result_count"] == 2
    assert [item.url for item in all_results] == ["local://weak", "https://example.edu/a"]


@pytest.mark.anyio
async def test_search_budget_and_execute_return_stable_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = _runtime()

    class SlowRetriever:
        name = "slow"

        async def traced_search(self, _query: str, *, max_results: int) -> list[SearchResult]:
            await asyncio.sleep(0.02)
            return [_result("https://slow.example", "Slow", "late")]

    class FailingRetriever:
        name = "failing"

        async def traced_search(self, _query: str, *, max_results: int) -> list[SearchResult]:
            raise RuntimeError("provider down")

    class FakeLocalRetriever:
        name = "local_rag"

        def __init__(self, *args, **kwargs) -> None:
            pass

        async def traced_search(self, query: str, *, max_results: int) -> list[SearchResult]:
            return [_result("local://matrix", "Matrix", f"{query} 本地材料", source="local_rag")]

    class FakeCompressor:
        def __init__(self, _context) -> None:
            pass

        async def run(self, **kwargs):
            return SimpleNamespace(content="矩阵 本地材料 已压缩", metadata={"compression_mode": "extractive"})

    class FakeCurator:
        def __init__(self, _context) -> None:
            pass

        async def curate_sources(self, *, sources, **_kwargs):
            return list(sources), {
                "selected_count": len(sources),
                "trusted_source_count": 1,
                "local_source_count": len([item for item in sources if item.url.startswith("local://")]),
                "web_source_count": 0,
                "unique_domain_count": 1,
                "top_domains": {"local": 1},
            }

    async def fake_generate_sub_queries(*_args, **_kwargs):
        return ["矩阵 例题", "矩阵 例题"]

    budget_low = await runtime._search_with_budget(
        SlowRetriever(),
        query="矩阵",
        max_results=1,
        provider_budget_s=0.1,
        retrieval_started_at=0.0,
        retrieval_budget_s=0.5,
    )
    failed = await runtime._search_with_budget(
        FailingRetriever(),
        query="矩阵",
        max_results=1,
        provider_budget_s=0.1,
        retrieval_started_at=0.0,
        retrieval_budget_s=3600.0,
    )

    monkeypatch.setattr(
        chapter_context_module,
        "get_settings",
        lambda: SimpleNamespace(
            docgen=SimpleNamespace(allow_external_search=False),
            rag=SimpleNamespace(similarity_threshold=0.2),
            local_rag=SimpleNamespace(min_results=1),
        ),
    )
    monkeypatch.setattr(chapter_context_module, "generate_sub_queries", fake_generate_sub_queries)
    monkeypatch.setattr(chapter_context_module, "LocalRAGRetriever", FakeLocalRetriever)
    monkeypatch.setattr(chapter_context_module, "get_retrievers_for_course", lambda **_kwargs: [])
    monkeypatch.setattr(
        chapter_context_module,
        "get_configured_retriever_names",
        lambda **_kwargs: ["local_rag"],
    )
    monkeypatch.setattr(chapter_context_module, "ContextCompressor", FakeCompressor)
    monkeypatch.setattr(chapter_context_module, "SourceCurator", FakeCurator)

    empty = await runtime.execute(queries=[], chapter_title="", objective="")
    result = await runtime.execute(
        queries=["矩阵"],
        local_rag_course_id="course_docgen0000",
        chapter_title="矩阵",
        objective="",
        required_elements=[],
        digest_mode="systematic",
        max_research_rounds=1,
        query_cap=3,
        queries_per_round=1,
    )

    assert budget_low == []
    assert failed == []
    assert empty.metadata == {"local_hits": 0, "web_hits": 0, "query_count": 0}
    assert result.content == "矩阵 本地材料 已压缩"
    assert result.metadata["local_hits"] == 1
    assert result.metadata["web_hits"] == 0
    assert result.metadata["query_count"] == 1
    assert result.metadata["research_round_count"] == 1
    assert result.metadata["stop_reason"] == "coverage_target_met"
    assert result.metadata["compression_mode"] == "extractive"
    assert result.metadata["configured_retrievers"] == ["local_rag"]
