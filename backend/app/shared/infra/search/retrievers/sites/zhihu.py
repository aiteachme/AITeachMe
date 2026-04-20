"""Zhihu site-specific retriever."""

from __future__ import annotations

from app.shared.infra.search.retrievers.sites.duckduckgo_site import DuckDuckGoSiteRetriever


class ZhihuRetriever(DuckDuckGoSiteRetriever):
    """Search Zhihu as a Chinese community discussion fallback."""

    auto_register = True
    canonical_name = "zhihu"
    aliases = ("zhihu",)
    site_query_domain = "zhihu.com"
    allowed_domains = ("zhihu.com",)
    title_suffixes = (" - 知乎",)


__all__ = ["ZhihuRetriever"]
