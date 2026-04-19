"""MCP tool-backed search retriever."""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.shared.infra.env_support import get_env
from app.shared.infra.mcp import get_mcp_manager
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.retrievers.common import clamp_max_results, make_search_result, normalize_query
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


class MCPSearchRetriever(BaseRetriever):
    canonical_name = "mcp_search"
    aliases = ("mcp", "mcp_research")
    cacheable = False

    @classmethod
    def _tool_name(cls) -> str:
        return (get_env("MCP_SEARCH_TOOL") or "").strip()

    @classmethod
    def is_available(cls) -> bool:
        return bool(cls._tool_name())

    @classmethod
    def availability_reason(cls) -> str | None:
        if cls.is_available():
            return None
        return "missing `MCP_SEARCH_TOOL`"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = normalize_query(query)
        tool_name = self._tool_name()
        if not normalized_query or not tool_name:
            return []
        count = clamp_max_results(max_results, upper=20)
        query_arg = (get_env("MCP_SEARCH_QUERY_ARG", "query") or "query").strip()
        max_arg = (get_env("MCP_SEARCH_MAX_RESULTS_ARG", "max_results") or "max_results").strip()
        try:
            result = await get_mcp_manager().call_tool(tool_name, **{query_arg: normalized_query, max_arg: count})
        except Exception as exc:  # pragma: no cover - depends on external MCP runtime
            logger.warning("mcp_search_failed", tool=tool_name, error=str(exc), query=normalized_query)
            return []
        return self._parse_tool_result(result, count=count)

    def _parse_tool_result(self, result: Any, *, count: int) -> list[SearchResult]:
        payload = result
        if isinstance(result, str):
            try:
                payload = json.loads(result)
            except json.JSONDecodeError:
                return []
        if isinstance(payload, dict):
            values = payload.get("results") or payload.get("items") or payload.get("data") or payload.get("documents") or []
        else:
            values = payload
        if not isinstance(values, list):
            return []

        results: list[SearchResult] = []
        for item in values:
            if isinstance(item, str):
                continue
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("href") or item.get("link")
            title = item.get("title") or item.get("name") or url
            snippet = item.get("snippet") or item.get("body") or item.get("content") or item.get("raw_content") or item.get("text")
            parsed = make_search_result(url=url, title=title, snippet=snippet, source=self.name, snippet_limit=1600)
            if parsed is not None:
                results.append(parsed)
            if len(results) >= count:
                break
        return results


__all__ = ["MCPSearchRetriever"]
