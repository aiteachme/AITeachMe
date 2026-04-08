"""Retriever factory helpers."""

from __future__ import annotations

from app.shared.infra.config import get_settings
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.bing import BingRetriever
from app.shared.infra.search.retrievers.bocha import BochaRetriever
from app.shared.infra.search.retrievers.duckduckgo import DuckDuckGoRetriever
from app.shared.infra.search.retrievers.local_rag import LocalRAGRetriever
from app.shared.infra.search.scraper.bs4_scraper import BS4Scraper
from app.shared.infra.search.scraper.pdf_scraper import PDFScraper


def get_retriever(
    name: str,
    *,
    subject: str | None = None,
    local_sections: list[object] | None = None,
) -> BaseRetriever:
    normalized = (name or "").strip().lower()
    if normalized in {"local_rag", "rag"}:
        return LocalRAGRetriever(subject=subject, local_sections=local_sections)
    if normalized in {"duckduckgo", "ddg"}:
        return DuckDuckGoRetriever()
    if normalized == "bing":
        return BingRetriever()
    if normalized == "bocha":
        return BochaRetriever()
    raise ValueError(f"Unknown retriever: {name}")


def get_retrievers_for_subject(
    *,
    subject: str | None = None,
    local_sections: list[object] | None = None,
) -> list[BaseRetriever]:
    settings = get_settings()
    retrievers: list[BaseRetriever] = []
    if settings.local_rag_priority and (subject or local_sections):
        retrievers.append(get_retriever("local_rag", subject=subject, local_sections=local_sections))
    primary = (settings.web_search_retriever or "duckduckgo").strip().lower()
    if primary:
        try:
            retrievers.append(get_retriever(primary, subject=subject, local_sections=local_sections))
        except ValueError:
            pass
    if primary != "duckduckgo":
        retrievers.append(get_retriever("duckduckgo", subject=subject, local_sections=local_sections))
    return retrievers


def get_scraper_for_url(url: str):
    normalized = (url or "").lower()
    if normalized.endswith(".pdf") or ".pdf?" in normalized:
        return PDFScraper()
    return BS4Scraper()


__all__ = ["get_retriever", "get_retrievers_for_subject", "get_scraper_for_url"]
