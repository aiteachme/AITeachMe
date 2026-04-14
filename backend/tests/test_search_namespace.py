import asyncio

from app.shared.infra.search import (
    RetrievalConfig,
    RetrievalPipeline,
    RetrievedChunk,
    get_external_retriever_names,
    get_registered_reader_names,
    get_registered_retriever_names,
    get_reader_for_url,
    rerank_chunks,
)
from app.shared.infra.search.knowledge import (
    RetrievalConfig as CanonicalRetrievalConfig,
    RetrievalPipeline as CanonicalRetrievalPipeline,
    RetrievedChunk as CanonicalRetrievedChunk,
    rerank_chunks as canonical_rerank_chunks,
)
from app.shared.infra.search.retrievers.duckduckgo import _parse_duckduckgo_html_results
from app.shared.infra.search.retrievers.local_rag import LocalRAGRetriever
from app.shared.infra.search.retrievers.wikipedia import WikipediaRetriever
from app.shared.infra.search.readers import BS4Reader, DOCXReader, PDFReader, PPTXReader, TextReader


def test_search_package_exposes_canonical_knowledge_contracts() -> None:
    assert RetrievalConfig is CanonicalRetrievalConfig
    assert RetrievalPipeline is CanonicalRetrievalPipeline
    assert RetrievedChunk is CanonicalRetrievedChunk
    assert rerank_chunks is canonical_rerank_chunks


def test_reader_factory_resolves_expected_reader_types() -> None:
    pdf_url = "https://example.com/sample.pdf"
    docx_url = "https://example.com/sample.docx"
    pptx_url = "https://example.com/sample.pptx"
    md_url = "https://example.com/notes.md"
    html_url = "https://example.com/course/page"

    assert isinstance(get_reader_for_url(pdf_url), PDFReader)
    assert isinstance(get_reader_for_url(docx_url), DOCXReader)
    assert isinstance(get_reader_for_url(pptx_url), PPTXReader)
    assert isinstance(get_reader_for_url(md_url), TextReader)
    assert isinstance(get_reader_for_url(html_url), BS4Reader)


def test_external_retriever_names_exclude_local_rag_aliases() -> None:
    names = get_external_retriever_names()
    assert "local_rag" not in names
    assert "rag" not in names


def test_registered_search_tool_names_are_exposed() -> None:
    reader_names = get_registered_reader_names()
    retriever_names = get_registered_retriever_names()

    assert {"bs4", "pdf", "docx", "pptx", "text"}.issubset(set(reader_names))
    assert {"duckduckgo", "bing", "bocha", "semantic_scholar", "arxiv", "tavily", "local_rag", "wikipedia", "searxng"}.issubset(
        set(retriever_names)
    )


def test_local_rag_prefers_uploaded_sections_before_vector_search(monkeypatch) -> None:
    section = {
        "title": "计算机基础",
        "normalized_content": "计算机基础知识 包括 操作系统 网络 数据结构 和 算法。",
    }
    retriever = LocalRAGRetriever(subject="subj_demo", local_sections=[section])
    called = {"notice": 0, "search": 0}

    async def fake_notice(_subject: str) -> str | None:
        called["notice"] += 1
        return "当前学科向量检索暂不可用。"

    async def fake_search(*_args, **_kwargs):
        called["search"] += 1
        return []

    monkeypatch.setattr(
        "app.shared.infra.search.retrievers.local_rag.get_knowledge_search_notice",
        fake_notice,
    )
    monkeypatch.setattr(
        "app.shared.infra.search.retrievers.local_rag.search_knowledge",
        fake_search,
    )

    results = asyncio.run(retriever.search("计算机基础", max_results=3))

    assert called["notice"] == 0
    assert called["search"] == 0
    assert results
    assert results[0].source == "local_rag"
    assert results[0].url.startswith("local://section/")


def test_local_rag_is_not_runtime_cacheable() -> None:
    assert LocalRAGRetriever.cacheable is False


def test_local_rag_section_fallback_supports_cjk_ngram_overlap() -> None:
    retriever = LocalRAGRetriever(
        local_sections=[
            {
                "title": "线性代数基础",
                "normalized_content": "这里系统讲解向量空间的判定方法、基与维数之间的联系。",
            }
        ]
    )

    results = asyncio.run(retriever.search("向量空间 判别", max_results=3))

    assert results
    assert results[0].title == "线性代数基础"


def test_duckduckgo_html_parser_extracts_result_cards() -> None:
    html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.edu%2Fcourse">线性代数课程笔记</a>
          <a class="result__snippet">覆盖向量空间、基与维数的核心概念。</a>
        </div>
      </body>
    </html>
    """

    results = _parse_duckduckgo_html_results(html, max_results=3)

    assert len(results) == 1
    assert results[0].url == "https://example.edu/course"
    assert results[0].title == "线性代数课程笔记"
    assert "向量空间" in results[0].snippet


def test_duckduckgo_html_parser_extracts_lite_results_with_adjacent_snippet_rows() -> None:
    html = """
    <html>
      <body>
        <table>
          <tr>
            <td>1.</td>
            <td><a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fdeterminant">行列式展开详解</a></td>
          </tr>
          <tr>
            <td></td>
            <td class="result-snippet">覆盖按行展开、按列展开和拉普拉斯展开。</td>
          </tr>
        </table>
      </body>
    </html>
    """

    results = _parse_duckduckgo_html_results(html, max_results=3)

    assert len(results) == 1
    assert results[0].url == "https://example.org/determinant"
    assert "拉普拉斯展开" in results[0].snippet


def test_wikipedia_retriever_queries_official_mediawiki_api(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "query": {
                    "search": [
                        {
                            "title": "向量空间",
                            "snippet": "向量空间是带有加法与数乘运算的代数结构。",
                        }
                    ]
                }
            }

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url: str, *, params: dict[str, object]):
            captured["url"] = url
            captured["params"] = params
            return FakeResponse()

    monkeypatch.setattr("app.shared.infra.search.retrievers.wikipedia.httpx.AsyncClient", lambda **_: FakeClient())

    results = asyncio.run(WikipediaRetriever().search("向量空间 定义", max_results=2))

    assert results
    assert "w/api.php" in str(captured["url"])
    assert captured["params"]["list"] == "search"
    assert results[0].title == "向量空间"
    assert results[0].url.startswith("https://zh.wikipedia.org/wiki/")
