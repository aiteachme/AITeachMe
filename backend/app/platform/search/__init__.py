"""搜索与检索 — 对外极简 API。"""
from app.platform.search.api import search_knowledge, web_search
from app.platform.search.types import WebSearchResult

__all__ = [
    "search_knowledge",
    "web_search",
    "WebSearchResult",
]
