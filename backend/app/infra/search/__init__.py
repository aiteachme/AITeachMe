"""搜索与检索 — 对外极简 API。

外部使用方式::

    from app.infra.search import web_search, search_knowledge

    # Web 搜索
    results = await web_search("贝叶斯定理 教程")

    # 知识库检索
    chunks = await search_knowledge("特征值", subject_id="linear-algebra")
"""

from app.infra.search.api import search_knowledge, web_search
from app.infra.search.types import WebSearchResult

__all__ = [
    "search_knowledge",
    "web_search",
    "WebSearchResult",
]
