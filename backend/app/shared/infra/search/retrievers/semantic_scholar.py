"""Semantic Scholar retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.settings import get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, clean_text, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


class SemanticScholarRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "semantic_scholar"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query:
            return []
        settings = get_settings()
        count = clamp_max_results(max_results, upper=50)
        params = {
            "query": normalized_query,
            "limit": count,
            "fields": "title,abstract,url,openAccessPdf,isOpenAccess,year,venue",
        }
        headers: dict[str, str] = {}
        api_key = (get_env("SEMANTIC_SCHOLAR_API_KEY") or "").strip()
        if api_key:
            headers["x-api-key"] = api_key
        try:
            async with httpx.AsyncClient(timeout=settings.search.provider_timeout_s) as client:
                response = await client.get(_SEMANTIC_SCHOLAR_URL, params=params, headers=headers)
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("semantic_scholar_search_failed", error=str(exc), query=normalized_query)
            return []

        values = response.json().get("data") or []
        results: list[SearchResult] = []
        for item in values:
            snippet = clean_text(item.get("abstract"), limit=1000)
            open_access_pdf = item.get("openAccessPdf") or {}
            url = str(open_access_pdf.get("url") or item.get("url") or "").strip()
            venue = clean_text(item.get("venue"))
            year = clean_text(item.get("year"))
            suffix = ", ".join(bit for bit in [venue, year] if bit)
            if suffix and snippet:
                snippet = f"{snippet} [{suffix}]"
            elif suffix:
                snippet = suffix
            result = make_search_result(
                url=url,
                title=item.get("title"),
                snippet=snippet,
                source=self.name,
            )
            if result is not None:
                results.append(result)
            if len(results) >= count:
                break
        return results


__all__ = ["SemanticScholarRetriever"]
