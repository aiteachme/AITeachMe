"""Curated site-specific retrievers.

This package keeps one-domain adapters separate from general web search
providers. Some of them are open educational resources (OER); others are
ordinary site-constrained fallbacks.
"""

from .baidu_baike import BaiduBaikeRetriever
from .duckduckgo_site import DuckDuckGoSiteRetriever
from .mediawiki import MediaWikiSiteRetriever
from .oi_wiki import OIWikiRetriever
from .zh_wikis import (
    ZhWikibooksRetriever,
    ZhWikipediaRetriever,
    ZhWiktionaryRetriever,
    ZhWikiversityRetriever,
)
from .zhihu import ZhihuRetriever

__all__ = [
    "BaiduBaikeRetriever",
    "DuckDuckGoSiteRetriever",
    "MediaWikiSiteRetriever",
    "OIWikiRetriever",
    "ZhihuRetriever",
    "ZhWikibooksRetriever",
    "ZhWikipediaRetriever",
    "ZhWiktionaryRetriever",
    "ZhWikiversityRetriever",
]
