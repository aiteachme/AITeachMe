"""Reusable URL reading helpers for research-oriented workflows."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from app.shared.infra.settings import get_settings
from app.shared.infra.observability.trace import sanitize_langsmith_input, traceable_with_context
from app.shared.infra.search.factory import get_reader_for_url
from app.shared.infra.search.types import ScrapedPage


def _read_urls_trace_inputs(inputs: dict[str, object]) -> dict[str, object]:
    urls = [str(url or "").strip() for url in list(inputs.get("urls") or []) if str(url or "").strip()]
    payload: dict[str, object] = {
        "url_count": len(urls),
        "preferred_reader": str(inputs.get("preferred_reader") or ""),
        "urls_preview": sanitize_langsmith_input(urls[:2], field_name="urls"),
    }
    max_workers = inputs.get("max_workers")
    if max_workers not in (None, ""):
        payload["max_workers"] = int(max_workers)
    timeout_s = inputs.get("timeout_s")
    if timeout_s not in (None, ""):
        payload["timeout_s"] = float(timeout_s)
    return payload


def _read_urls_trace_outputs(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        return {}
    trace = payload.get("trace")
    if isinstance(trace, Mapping):
        return dict(trace)
    return {}


def _page_trace_preview(page: ScrapedPage) -> dict[str, object]:
    content_preview = " ".join(str(page.content or "").split())
    if len(content_preview) > 360:
        content_preview = content_preview[:360].rstrip() + "..."
    return {
        "url": page.url,
        "title": page.title,
        "success": page.success,
        "reader_name": page.reader_name,
        "content_length": len(page.content),
        "content_preview": content_preview,
        "error": page.error or "",
    }


@traceable_with_context(
    name="tool.read_urls",
    run_type="tool",
    process_inputs=_read_urls_trace_inputs,
    process_outputs=_read_urls_trace_outputs,
    metadata_factory=lambda urls, max_workers=None, preferred_reader=None, timeout_s=None: {"tool_name": "read_urls"},
    tags_factory=lambda urls, max_workers=None, preferred_reader=None, timeout_s=None: ["tool:read_urls"],
)
async def _run_traced_read_urls(
    urls: list[str],
    *,
    max_workers: int,
    preferred_reader: str | None,
    timeout_s: float | None,
    langsmith_extra: dict[str, object] | None = None,
) -> dict[str, object]:
    del langsmith_extra
    ordered_urls = list(dict.fromkeys(str(url or "").strip() for url in urls if str(url or "").strip()))
    semaphore = asyncio.Semaphore(max_workers)

    async def _read_one(url: str) -> ScrapedPage:
        async with semaphore:
            reader = get_reader_for_url(url, preferred=preferred_reader) if preferred_reader else get_reader_for_url(url)
            try:
                if timeout_s is not None and timeout_s > 0:
                    return await asyncio.wait_for(reader.traced_read(url), timeout=timeout_s)
                return await reader.traced_read(url)
            except Exception as exc:  # pragma: no cover - reader backends are integration-heavy
                return ScrapedPage(url=url, success=False, error=str(exc))

    pages = await asyncio.gather(*[_read_one(url) for url in ordered_urls])
    return {
        "pages": pages,
        "trace": {
            "page_count": len(pages),
            "success_count": sum(1 for page in pages if page.success),
            "pages_preview": [_page_trace_preview(page) for page in pages[:5]],
        },
    }


async def read_urls(
    urls: list[str],
    *,
    max_workers: int | None = None,
    preferred_reader: str | None = None,
    timeout_s: float | None = None,
) -> list[ScrapedPage]:
    """Read URLs concurrently with stable ordering and URL deduplication."""

    ordered_urls = list(dict.fromkeys(str(url or "").strip() for url in urls if str(url or "").strip()))
    if not ordered_urls:
        return []

    settings = get_settings()
    worker_count = max(1, int(max_workers or settings.docgen.io_parallelism or 1))
    payload = await _run_traced_read_urls(
        ordered_urls,
        max_workers=worker_count,
        preferred_reader=preferred_reader,
        timeout_s=timeout_s or settings.search.read_timeout_s,
    )
    return list(payload.get("pages") or [])


__all__ = ["read_urls"]
