"""Web 搜索实现 — 自动选择可用提供商。

提供商优先级：
1. DuckDuckGo（免费，无需 API Key，默认可用）
2. TODO: Serper / Tavily 等付费提供商（需配置 Key）
"""

from __future__ import annotations

import structlog

from app.core.search.types import WebSearchResult

logger = structlog.get_logger()


async def search_duckduckgo(query: str, *, top_k: int = 5) -> list[WebSearchResult]:
    """使用 DuckDuckGo 搜索（免费，无需 API Key）。

    依赖 ``duckduckgo-search`` 库，未安装时返回空结果。
    """

    try:
        from duckduckgo_search import AsyncDDGS
    except ImportError:
        logger.warning("web_search_provider_unavailable",
                       provider="duckduckgo",
                       reason="duckduckgo-search 未安装，请运行 pip install duckduckgo-search")
        return []

    try:
        async with AsyncDDGS() as ddgs:
            results = await ddgs.atext(query, max_results=top_k)
            return [
                WebSearchResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    snippet=r.get("body", ""),
                )
                for r in results
            ]
    except Exception as exc:
        logger.warning("web_search_failed", provider="duckduckgo", error=str(exc))
        return []


async def dispatch_web_search(query: str, *, top_k: int = 5) -> list[WebSearchResult]:
    """自动选择可用的搜索提供商并执行搜索。"""

    # 当前只有 DuckDuckGo，后续扩展其他提供商
    results = await search_duckduckgo(query, top_k=top_k)

    if results:
        logger.info("web_search_complete",
                     provider="duckduckgo",
                     query_len=len(query),
                     result_count=len(results))

    return results
