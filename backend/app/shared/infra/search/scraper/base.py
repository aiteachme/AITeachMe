"""Base scraper abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.shared.infra.search.types import ScrapedPage
from app.shared.infra.tracing import get_llm_trace_context, langsmith_trace


class BaseScraper(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def scrape(self, url: str) -> ScrapedPage:
        raise NotImplementedError

    async def traced_scrape(self, url: str) -> ScrapedPage:
        trace = get_llm_trace_context()
        with langsmith_trace(
            name=f"scraper.{self.name}",
            run_type="tool",
            inputs={"url": url},
            subject=trace.subject,
            build_session_id=trace.build_session_id,
            workflow=trace.workflow,
            lane=trace.lane,
            node=trace.node,
            extra_metadata={"scraper_name": self.name},
            extra_tags=[f"scraper:{self.name}"],
        ) as run:
            result = await self.scrape(url)
            if run is not None:
                run.end(outputs={"success": result.success, "content_length": len(result.content)})
            return result


__all__ = ["BaseScraper"]
