"""Reusable URL reading helpers for research-oriented workflows."""

from __future__ import annotations

import asyncio

from app.shared.infra.config import get_settings
from app.shared.infra.search.factory import get_reader_for_url
from app.shared.infra.search.types import ScrapedPage
from app.shared.infra.observability import (
    get_llm_trace_context,
    langsmith_trace,
    sanitize_langsmith_input,
)


async def read_urls(
    urls: list[str],
    *,
    max_workers: int | None = None,
    preferred_reader: str | None = None,
) -> list[ScrapedPage]:
    """Read URLs concurrently with stable ordering and URL deduplication."""

    ordered_urls = list(dict.fromkeys(str(url or "").strip() for url in urls if str(url or "").strip()))
    if not ordered_urls:
        return []

    settings = get_settings()
    worker_count = max(1, int(max_workers or settings.docgen_io_parallelism or 1))
    semaphore = asyncio.Semaphore(worker_count)
    trace = get_llm_trace_context()

    async def _read_one(url: str) -> ScrapedPage:
        async with semaphore:
            reader = get_reader_for_url(url, preferred=preferred_reader) if preferred_reader else get_reader_for_url(url)
            try:
                return await reader.traced_read(url)
            except Exception as exc:  # pragma: no cover - reader backends are integration-heavy
                return ScrapedPage(url=url, success=False, error=str(exc))

    with langsmith_trace(
        name="tool.read_urls",
        run_type="tool",
        inputs={
            "url_count": len(ordered_urls),
            "max_workers": worker_count,
            "preferred_reader": preferred_reader or "",
            "urls_preview": sanitize_langsmith_input(ordered_urls[:2], field_name="urls"),
        },
        subject=trace.subject,
        build_session_id=trace.build_session_id,
        workflow=trace.workflow,
        lane=trace.lane,
        node=trace.node,
        extra_metadata={"tool_name": "read_urls"},
        extra_tags=["tool:read_urls"],
    ) as run:
        pages = await asyncio.gather(*[_read_one(url) for url in ordered_urls])
        if run is not None:
            run.end(
                outputs={
                    "page_count": len(pages),
                    "success_count": sum(1 for page in pages if page.success),
                }
            )
        return pages


__all__ = ["read_urls"]
