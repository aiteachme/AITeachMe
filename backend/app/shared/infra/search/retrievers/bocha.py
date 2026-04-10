"""Optional Bocha retriever placeholder."""

from __future__ import annotations

import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


class BochaRetriever(BaseRetriever):
    @property
    def name(self) -> str:
        return "bocha"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        settings = get_settings()
        if not settings.bocha_api_key:
            return []
        logger.info("bocha_search_not_implemented", query=query, max_results=max_results)
        return []


__all__ = ["BochaRetriever"]
