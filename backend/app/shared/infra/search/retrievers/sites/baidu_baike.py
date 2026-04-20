"""Baidu Baike site-specific retriever."""

from __future__ import annotations

from app.shared.infra.search.retrievers.sites.duckduckgo_site import DuckDuckGoSiteRetriever


class BaiduBaikeRetriever(DuckDuckGoSiteRetriever):
    """Search Baidu Baike as a Chinese encyclopedia fallback."""

    auto_register = True
    canonical_name = "baidu_baike"
    aliases = ("baike",)
    site_query_domain = "baike.baidu.com"
    allowed_domains = ("baike.baidu.com",)
    title_suffixes = ("_百度百科", " - 百度百科")


__all__ = ["BaiduBaikeRetriever"]
