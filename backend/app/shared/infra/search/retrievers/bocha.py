"""Optional Bocha retriever placeholder."""

from __future__ import annotations

import structlog

from app.shared.infra.env_support import get_env
from app.shared.infra.search.retrievers.base import BaseRetriever
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


class BochaRetriever(BaseRetriever):
    @classmethod
    def is_available(cls) -> bool:
        return False

    @classmethod
    def availability_reason(cls) -> str | None:
        if not (get_env("BOCHA_API_KEY") or "").strip():
            return "missing `BOCHA_API_KEY`"
        return "provider implementation is not completed yet"

    @property
    def name(self) -> str:
        return "bocha"

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not get_env("BOCHA_API_KEY"):
            return []
        logger.info("bocha_search_not_implemented", query=query, max_results=max_results)
        return []


__all__ = ["BochaRetriever"]
