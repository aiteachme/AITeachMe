"""Chinese Wikimedia OER retrievers."""

from __future__ import annotations

from app.shared.infra.search.retrievers.sites.mediawiki import MediaWikiSiteRetriever


class ZhWikipediaRetriever(MediaWikiSiteRetriever):
    """Chinese Wikipedia, useful for broad concept definitions."""

    auto_register = True
    canonical_name = "zh_wikipedia"
    aliases = ("wikipedia_zh", "zh_wiki")
    api_url = "https://zh.wikipedia.org/w/api.php"
    page_base_url = "https://zh.wikipedia.org/wiki"
    site_label = "中文维基百科"


class ZhWikibooksRetriever(MediaWikiSiteRetriever):
    """Chinese Wikibooks, useful for textbook-like explanations."""

    auto_register = True
    canonical_name = "zh_wikibooks"
    aliases = ("wikibooks_zh", "zh_wikibook")
    api_url = "https://zh.wikibooks.org/w/api.php"
    page_base_url = "https://zh.wikibooks.org/wiki"
    site_label = "中文维基教科书"


class ZhWikiversityRetriever(MediaWikiSiteRetriever):
    """Chinese Wikiversity, useful for course-like learning pages."""

    auto_register = True
    canonical_name = "zh_wikiversity"
    aliases = ("wikiversity_zh",)
    api_url = "https://zh.wikiversity.org/w/api.php"
    page_base_url = "https://zh.wikiversity.org/wiki"
    site_label = "中文维基学院"


class ZhWiktionaryRetriever(MediaWikiSiteRetriever):
    """Chinese Wiktionary, useful for terminology and word definitions."""

    auto_register = True
    canonical_name = "zh_wiktionary"
    aliases = ("wiktionary_zh",)
    api_url = "https://zh.wiktionary.org/w/api.php"
    page_base_url = "https://zh.wiktionary.org/wiki"
    site_label = "中文维基词典"


__all__ = [
    "ZhWikibooksRetriever",
    "ZhWiktionaryRetriever",
    "ZhWikiversityRetriever",
    "ZhWikipediaRetriever",
]
