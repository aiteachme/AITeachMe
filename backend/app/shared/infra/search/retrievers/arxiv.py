"""arXiv retriever."""

from __future__ import annotations

from urllib.parse import quote_plus
from xml.etree import ElementTree

import httpx
import structlog

from app.shared.infra.settings import get_settings
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


class ArxivRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "arxiv"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        settings = get_settings()
        count = clamp_max_results(max_results, upper=50)
        api_url = (
            "https://export.arxiv.org/api/query"
            f"?search_query=all:{quote_plus(normalized_query)}&start=0&max_results={count}&sortBy=relevance&sortOrder=descending"
        )
        try:
            async with httpx.AsyncClient(timeout=settings.search.provider_timeout_s) as client:
                response = await client.get(api_url)
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("arxiv_search_failed", error=str(exc), query=normalized_query)
            return []

        try:
            root = ElementTree.fromstring(response.text)
        except ElementTree.ParseError as exc:  # pragma: no cover - provider behavior
            logger.warning("arxiv_parse_failed", error=str(exc), query=query)
            return []

        results: list[SearchResult] = []
        for entry in root.findall("atom:entry", _ATOM_NS):
            title = _clean_xml_text(entry.findtext("atom:title", default="", namespaces=_ATOM_NS))
            summary = _clean_xml_text(entry.findtext("atom:summary", default="", namespaces=_ATOM_NS))
            url = _extract_entry_url(entry)
            result = make_search_result(
                url=url,
                title=title,
                snippet=summary,
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


def _clean_xml_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip()


def _extract_entry_url(entry: ElementTree.Element) -> str:
    for link in entry.findall("atom:link", _ATOM_NS):
        href = str(link.attrib.get("href") or "").strip()
        title = str(link.attrib.get("title") or "").strip().lower()
        link_type = str(link.attrib.get("type") or "").strip().lower()
        if title == "pdf" and href:
            return href
        if link_type == "application/pdf" and href:
            return href
    return _clean_xml_text(entry.findtext("atom:id", default="", namespaces=_ATOM_NS))


__all__ = ["ArxivRetriever"]
