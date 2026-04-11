import importlib

from app.shared.infra import reranker as reranker_shim
from app.shared.infra import retrievers as retriever_shim
from app.shared.infra.search import (
    RetrievalConfig,
    RetrievalPipeline,
    RetrievedChunk,
    get_external_retriever_names,
    get_registered_reader_names,
    get_registered_retriever_names,
    get_reader_for_url,
    get_scraper_for_url,
    rerank_chunks,
)
from app.shared.infra.search.knowledge import (
    RetrievalConfig as CanonicalRetrievalConfig,
    RetrievalPipeline as CanonicalRetrievalPipeline,
    RetrievedChunk as CanonicalRetrievedChunk,
    rerank_chunks as canonical_rerank_chunks,
)
from app.shared.infra.search.readers import BS4Scraper, DOCXScraper, PDFScraper, PPTXScraper, TextScraper


def test_search_package_exposes_canonical_knowledge_contracts() -> None:
    assert RetrievalConfig is CanonicalRetrievalConfig
    assert RetrievalPipeline is CanonicalRetrievalPipeline
    assert RetrievedChunk is CanonicalRetrievedChunk
    assert rerank_chunks is canonical_rerank_chunks


def test_compatibility_shims_point_to_search_namespace() -> None:
    assert retriever_shim.RetrievalConfig is CanonicalRetrievalConfig
    assert retriever_shim.RetrievalPipeline is CanonicalRetrievalPipeline
    assert retriever_shim.RetrievedChunk is CanonicalRetrievedChunk
    assert reranker_shim.rerank_chunks is canonical_rerank_chunks


def test_reader_and_scraper_factories_resolve_same_underlying_reader() -> None:
    pdf_url = "https://example.com/sample.pdf"
    docx_url = "https://example.com/sample.docx"
    pptx_url = "https://example.com/sample.pptx"
    md_url = "https://example.com/notes.md"
    html_url = "https://example.com/course/page"

    assert isinstance(get_reader_for_url(pdf_url), PDFScraper)
    assert isinstance(get_scraper_for_url(pdf_url), PDFScraper)
    assert isinstance(get_reader_for_url(docx_url), DOCXScraper)
    assert isinstance(get_scraper_for_url(docx_url), DOCXScraper)
    assert isinstance(get_reader_for_url(pptx_url), PPTXScraper)
    assert isinstance(get_scraper_for_url(pptx_url), PPTXScraper)
    assert isinstance(get_reader_for_url(md_url), TextScraper)
    assert isinstance(get_scraper_for_url(md_url), TextScraper)
    assert isinstance(get_reader_for_url(html_url), BS4Scraper)
    assert isinstance(get_scraper_for_url(html_url), BS4Scraper)


def test_external_retriever_names_exclude_local_rag_aliases() -> None:
    names = get_external_retriever_names()
    assert "local_rag" not in names
    assert "rag" not in names


def test_registered_search_tool_names_are_exposed() -> None:
    reader_names = get_registered_reader_names()
    retriever_names = get_registered_retriever_names()

    assert {"bs4", "pdf", "docx", "pptx", "text"}.issubset(set(reader_names))
    assert {"duckduckgo", "bing", "bocha", "semantic_scholar", "arxiv", "tavily", "local_rag"}.issubset(
        set(retriever_names)
    )


def test_legacy_scraper_namespace_reexports_readers() -> None:
    legacy_scraper = importlib.import_module("app.shared.infra.search.scraper")
    legacy_base = importlib.import_module("app.shared.infra.search.scraper.base")

    assert legacy_scraper.PDFScraper is PDFScraper
    assert legacy_base.BaseReader.__name__ == "BaseReader"
