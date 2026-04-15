"""Semantic Scholar retriever."""

from __future__ import annotations

import httpx
import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.env_support import get_env
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)

_SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search"


class SemanticScholarRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "semantic_scholar"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        settings = get_settings()
        params = {
            "query": query,
            "limit": max_results,
            "fields": "title,abstract,url,openAccessPdf,isOpenAccess,year,venue",
        }
        headers: dict[str, str] = {}
        api_key = (get_env("SEMANTIC_SCHOLAR_API_KEY") or "").strip()
        if api_key:
            headers["x-api-key"] = api_key
        try:
            async with httpx.AsyncClient(timeout=settings.search_provider_timeout_s) as client:
                response = await client.get(_SEMANTIC_SCHOLAR_URL, params=params, headers=headers)
                response.raise_for_status()
        except Exception as exc:  # pragma: no cover - provider behavior
            logger.warning("semantic_scholar_search_failed", error=str(exc), query=query)
            return []

        values = response.json().get("data") or []
        results: list[SearchResult] = []
        for item in values:
            title = " ".join(str(item.get("title") or "").split()).strip()
            snippet = " ".join(str(item.get("abstract") or "").split()).strip()
            open_access_pdf = item.get("openAccessPdf") or {}
            url = str(open_access_pdf.get("url") or item.get("url") or "").strip()
            if not url:
                continue
            venue = " ".join(str(item.get("venue") or "").split()).strip()
            year = str(item.get("year") or "").strip()
            suffix = ", ".join(bit for bit in [venue, year] if bit)
            if suffix and snippet:
                snippet = f"{snippet} [{suffix}]"
            elif suffix:
                snippet = suffix
            results.append(
                SearchResult(
                    url=url,
                    title=title,
                    snippet=snippet,
                    source=self.name,
                )
            )
        return results


__all__ = ["SemanticScholarRetriever"]

