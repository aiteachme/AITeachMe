"""Research facade over search, readers, source curation, and compression."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.shared.infra.config import get_settings
from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.search import ContextCompressor, SourceCurator
from app.shared.infra.search.factory import get_configured_retriever_names, get_retrievers_for_subject
from app.shared.infra.search.types import ScrapedPage, SearchResult
from app.shared.infra.tools.builtin.web_reading import read_urls as _read_urls

from .context import InfraContext, workflow_trace_context


@dataclass(slots=True)
class ResearchContext:
    """Unified research payload for business/workflow layers."""

    query: str
    dense_context: str = ""
    sources: list[str] = field(default_factory=list)
    source_details: list[dict[str, object]] = field(default_factory=list)
    pages: list[ScrapedPage] = field(default_factory=list)
    local_hits: int = 0
    web_hits: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


async def read_sources(
    ctx: InfraContext,
    urls: list[str],
    *,
    max_workers: int | None = None,
    timeout_s: float | None = None,
) -> list[ScrapedPage]:
    """Read URLs through the shared reader stack."""

    del ctx
    return await _read_urls(urls, max_workers=max_workers, timeout_s=timeout_s)


def _traced_context(ctx: InfraContext, *, node: str) -> TracedExecutionContext:
    scoped = ctx.with_node(node)
    return TracedExecutionContext(
        subject=scoped.subject,
        build_session_id=scoped.build_session_id,
        workflow_context=workflow_trace_context(scoped),
        extra_metadata=scoped.trace_metadata(),
    )


async def _search_one(retriever, query: str, *, max_results: int, timeout_s: float) -> list[SearchResult]:
    try:
        return await asyncio.wait_for(
            retriever.traced_search(query, max_results=max_results),
            timeout=max(0.1, timeout_s),
        )
    except Exception:
        return []


def _search_result_documents(results: list[SearchResult], pages: list[ScrapedPage]) -> list[str]:
    documents: list[str] = []
    page_by_url = {page.url: page for page in pages}
    for item in results:
        if item.url.startswith("local://"):
            text = item.to_text()
            if text.strip():
                documents.append(text)
            continue
        page = page_by_url.get(item.url)
        if page is not None and page.success and page.content.strip():
            title = page.title.strip() or item.title.strip() or item.url
            documents.append(f"# {title}\n\n{page.content.strip()}")
            continue
        if item.snippet.strip():
            documents.append(item.to_text())
    return documents


async def build_research_context(
    ctx: InfraContext,
    *,
    query: str,
    local_sections: list[object] | None = None,
    profile: str | None = None,
    max_sources: int = 5,
    max_results_per_query: int | None = None,
    read: bool = True,
    compress: bool = True,
    focus_terms: list[str] | None = None,
) -> ResearchContext:
    """Build a curated, optionally deep-read and compressed research context."""

    settings = get_settings()
    query_text = str(query or "").strip()
    if not query_text:
        return ResearchContext(query="")

    per_query = max_results_per_query or settings.search_max_results_per_query
    retrievers = get_retrievers_for_subject(
        subject=ctx.subject,
        local_sections=local_sections,
        profile=profile,
        include_local_rag=bool(ctx.subject or local_sections),
        include_fallback=True,
    )
    configured_retrievers = get_configured_retriever_names(
        profile=profile,
        include_local_rag=bool(ctx.subject or local_sections),
        include_fallback=True,
    )
    all_results: list[SearchResult] = []
    retriever_stats: dict[str, dict[str, object]] = {}
    local_hits = 0
    web_hits = 0

    for retriever in retrievers:
        results = await _search_one(
            retriever,
            query_text,
            max_results=per_query,
            timeout_s=float(settings.search_provider_timeout_s),
        )
        retriever_stats[retriever.name] = {
            "query_count": 1,
            "result_count": len(results),
        }
        all_results.extend(results)
        if retriever.name == "local_rag":
            local_hits += len(results)
            if local_hits >= settings.local_rag_min_results:
                break
            continue
        web_hits += len(results)
        if len(all_results) >= max_sources:
            break

    curator = SourceCurator(_traced_context(ctx, node="facade.research.curate"))
    curated, curator_metadata = await curator.curate_sources(
        query=query_text,
        sources=all_results,
        max_results=max_sources,
    )

    external_urls = [
        item.url
        for item in curated
        if item.url and not item.url.startswith("local://")
    ]
    pages = (
        await read_sources(
            ctx.with_node("facade.research.read"),
            external_urls,
            max_workers=min(len(external_urls), settings.docgen_io_parallelism) if external_urls else None,
            timeout_s=float(settings.search_read_timeout_s),
        )
        if read and external_urls
        else []
    )
    documents = _search_result_documents(curated, pages)
    dense_context = "\n\n".join(documents)
    compression_mode = "disabled"
    if compress and documents:
        compressor = ContextCompressor(_traced_context(ctx, node="facade.research.compress"))
        compressed = await compressor.run(
            query=query_text,
            documents=documents,
            focus_terms=focus_terms,
            max_results=8,
        )
        dense_context = compressed.content.strip()
        compression_mode = str(compressed.metadata.get("compression_mode") or "")

    metadata = {
        "configured_retrievers": configured_retrievers,
        "active_retrievers": [retriever.name for retriever in retrievers],
        "retriever_stats": retriever_stats,
        "curated_source_count": len(curated),
        "read_url_count": sum(1 for page in pages if page.success),
        "document_count": len(documents),
        "compression_mode": compression_mode,
        **curator_metadata,
    }
    return ResearchContext(
        query=query_text,
        dense_context=dense_context,
        sources=[item.url for item in curated if item.url],
        source_details=[item.to_dict() for item in curated],
        pages=pages,
        local_hits=local_hits,
        web_hits=web_hits,
        metadata=metadata,
    )


__all__ = [
    "ResearchContext",
    "build_research_context",
    "read_sources",
]
