"""搜索与检索 — 对外极简 API。

外部使用方式::

    from app.infra.search import get_knowledge_search_notice, search_knowledge, web_search

    # Web 搜索
    results = await web_search("贝叶斯定理 教程")

    # 知识库检索
    notice = await get_knowledge_search_notice("linear-algebra")
    if notice is None:
        chunks = await search_knowledge("特征值", subject_id="linear-algebra")
"""

from app.infra.search.api import (
    get_knowledge_search_notice,
    search_knowledge,
    web_search,
)
from app.infra.search.types import WebSearchResult

__all__ = [
    "get_knowledge_search_notice",
    "search_knowledge",
    "web_search",
    "WebSearchResult",
]
