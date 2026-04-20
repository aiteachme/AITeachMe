"""Site-constrained retrievers built on top of DuckDuckGo search."""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlparse

import structlog

from app.shared.infra.search.retrievers.common import clamp_max_results, normalize_query
from app.shared.infra.search.retrievers.duckduckgo import DuckDuckGoRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


def _domain_matches(url: str, allowed_domains: tuple[str, ...]) -> bool:
    domain = urlparse(str(url or "")).netloc.lower().strip()
    if domain.startswith("www."):
        domain = domain[4:]
    return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in allowed_domains)


class DuckDuckGoSiteRetriever(DuckDuckGoRetriever):
    """Base class for one-site search adapters.

    These retrievers are still powered by DuckDuckGo, but their contract is
    different from a general web provider: they deliberately constrain results
    to one curated domain.
    """

    auto_register = False
    cacheable = True
    site_query_domain: str = ""
    allowed_domains: tuple[str, ...] = ()
    title_suffixes: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return str(getattr(self, "canonical_name", "") or self.site_query_domain).strip().lower()

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        if not normalized_query or not self.site_query_domain:
            return []
        count = clamp_max_results(max_results, upper=20)
        site_query = f"{normalized_query} site:{self.site_query_domain}"

        logger.info(
            "site_search_started",
            retriever=self.name,
            original_query=normalized_query,
            site_domain=self.site_query_domain,
        )
        results = await super().search(site_query, max_results=count)
        return self._normalize_site_results(results, max_results=count)

    def _normalize_site_results(self, results: list[SearchResult], *, max_results: int) -> list[SearchResult]:
        allowed_domains = self.allowed_domains or (self.site_query_domain,)
        normalized: list[SearchResult] = []
        for item in results:
            if allowed_domains and not _domain_matches(item.url, allowed_domains):
                continue
            title = str(item.title or "").strip()
            for suffix in self.title_suffixes:
                title = title.replace(suffix, "").strip()
            normalized.append(
                replace(
                    item,
                    title=title or item.title,
                    source=self.name,
                )
            )
            if len(normalized) >= max_results:
                break
        return normalized


__all__ = ["DuckDuckGoSiteRetriever"]
