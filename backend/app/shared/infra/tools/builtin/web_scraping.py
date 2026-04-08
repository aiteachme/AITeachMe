"""Reusable web scraping helpers for research-oriented workflows."""

from __future__ import annotations

import asyncio

from app.shared.infra.config import get_settings
from app.shared.infra.search.factory import get_scraper_for_url
from app.shared.infra.search.types import ScrapedPage
from app.shared.infra.tracing import get_llm_trace_context, langsmith_trace


async def scrape_urls(
    urls: list[str],
    *,
    max_workers: int | None = None,
) -> list[ScrapedPage]:
    """Scrape URLs concurrently with stable ordering and URL deduplication."""

    ordered_urls = list(dict.fromkeys(str(url or "").strip() for url in urls if str(url or "").strip()))
    if not ordered_urls:
        return []

    settings = get_settings()
    worker_count = max(1, int(max_workers or settings.docgen_io_parallelism or 1))
    semaphore = asyncio.Semaphore(worker_count)
    trace = get_llm_trace_context()

    async def _scrape_one(url: str) -> ScrapedPage:
        async with semaphore:
            scraper = get_scraper_for_url(url)
            try:
                return await scraper.traced_scrape(url)
            except Exception as exc:  # pragma: no cover - scraper backends are integration-heavy
                return ScrapedPage(url=url, success=False, error=str(exc))

    with langsmith_trace(
        name="tool.scrape_urls",
        run_type="tool",
        inputs={"url_count": len(ordered_urls), "max_workers": worker_count},
        subject=trace.subject,
        build_session_id=trace.build_session_id,
        workflow=trace.workflow,
        lane=trace.lane,
        node=trace.node,
        extra_metadata={"tool_name": "scrape_urls"},
        extra_tags=["tool:scrape_urls"],
    ) as run:
        pages = await asyncio.gather(*[_scrape_one(url) for url in ordered_urls])
        if run is not None:
            run.end(
                outputs={
                    "page_count": len(pages),
                    "success_count": sum(1 for page in pages if page.success),
                }
            )
        return pages


__all__ = ["scrape_urls"]
