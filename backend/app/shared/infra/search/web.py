"""Multi-provider web search scheduler.

This module is intentionally lower-level than ``search.api``. It knows how to
fan out to configured retrievers, enforce a request budget, prefer local RAG
when available, and fuse multiple ranked provider result lists.

Workflow code should normally call ``app.shared.infra.search.web_search`` from
``api.py`` instead of importing this module directly.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import time

import structlog

from app.shared.infra.search.defaults import (
    DEFAULT_SEARCH_FUSION_K,
    DEFAULT_SEARCH_MAX_PARALLEL_RETRIEVERS,
    DEFAULT_SEARCH_PARALLEL_RETRIEVERS,
    DEFAULT_SEARCH_PROVIDER_TIMEOUT_S,
    DEFAULT_SEARCH_TOTAL_TIMEOUT_S,
)
from app.shared.infra.search.local_sufficiency import effective_local_result_count
from app.shared.infra.search.types import SearchResult

logger = structlog.get_logger(__name__)


async def _search_with_timeout(
    retriever,
    query: str,
    *,
    max_results: int,
    timeout_s: float,
) -> list[SearchResult]:
    """Run one retriever with an isolated timeout and failure boundary.

    External search providers fail often: rate limits, network issues, invalid
    keys, slow public pages, etc. Search should degrade by dropping that
    provider's results rather than breaking the whole workflow.
    """

    try:
        return await asyncio.wait_for(
            retriever.traced_search(query, max_results=max_results),
            timeout=max(0.1, timeout_s),
        )
    except asyncio.TimeoutError:
        logger.warning(
            "web_search_provider_timeout",
            provider=retriever.name,
            query=query,
            timeout_s=timeout_s,
        )
        return []
    except Exception as exc:
        logger.warning(
            "web_search_provider_failed",
            provider=retriever.name,
            query=query,
            error=str(exc),
        )
        return []


def _dedupe_key(item: SearchResult) -> str:
    """Build the key used to merge duplicate results across providers."""

    url = str(item.url or "").strip()
    if url:
        return url
    return f"{str(item.title or '').strip()}::{str(item.snippet or '').strip()[:160]}"


def _fuse_provider_results(
    provider_results: list[tuple[str, list[SearchResult]]],
    *,
    top_k: int,
    fusion_k: int,
) -> list[SearchResult]:
    """Fuse multi-provider ranked lists using a lightweight RRF variant.

    Each retriever returns an already-ranked list, but those scores are not
    comparable across providers. Reciprocal Rank Fusion lets us combine lists
    using rank position instead of trusting one provider's raw score. The small
    local RAG boost keeps uploaded course material preferred when it overlaps
    with public web results.
    """

    by_key: dict[str, tuple[SearchResult, float, set[str]]] = {}
    for provider_index, (provider_name, results) in enumerate(provider_results):
        provider_weight = 1.15 if provider_name == "local_rag" else 1.0
        provider_penalty = provider_index * 0.0001
        for rank, item in enumerate(results):
            key = _dedupe_key(item)
            if not key:
                continue
            lexical_score = max(0.0, float(item.score or 0.0)) * 0.05
            rrf_score = provider_weight / max(1.0, float(fusion_k + rank + 1))
            total = lexical_score + rrf_score - provider_penalty
            current = by_key.get(key)
            candidate = replace(
                item,
                score=total if current is None else max(float(current[0].score or 0.0), total),
                source=item.source or provider_name,
            )
            if current is None:
                by_key[key] = (candidate, total, {provider_name})
                continue

            existing_item, existing_score, providers = current
            providers.add(provider_name)
            combined_score = existing_score + total
            better_item = existing_item
            if len(candidate.snippet or "") > len(existing_item.snippet or ""):
                better_item = replace(candidate, score=combined_score)
            else:
                better_item = replace(existing_item, score=combined_score)
            if len(providers) > 1:
                better_item = replace(better_item, source="+".join(sorted(providers)))
            by_key[key] = (better_item, combined_score, providers)

    ranked = sorted(
        (replace(item, score=score) for item, score, _providers in by_key.values()),
        key=lambda item: (-float(item.score or 0.0), item.title.lower().strip(), item.url),
    )
    return ranked[:top_k]


async def _search_retrievers_parallel(
    retrievers: list[object],
    query: str,
    *,
    max_results: int,
    provider_timeout_s: float,
    total_deadline_s: float,
    started_at: float,
    max_parallel: int,
) -> list[tuple[str, list[SearchResult]]]:
    """Run external retrievers concurrently within one total deadline.

    Args:
        retrievers: Retriever instances to execute.
        query: Search query.
        max_results: Per-provider result cap.
        provider_timeout_s: Maximum time any single provider should spend.
        total_deadline_s: Maximum total time for this whole web search request.
        started_at: ``time.monotonic()`` value from the parent dispatch call.
        max_parallel: Concurrency cap to avoid fanning out too aggressively.

    Returns:
        ``(provider_name, results)`` pairs in the original retriever order.
    """

    semaphore = asyncio.Semaphore(max(1, max_parallel))

    async def _run_one(retriever) -> tuple[str, list[SearchResult]]:
        remaining = total_deadline_s - (time.monotonic() - started_at)
        if remaining <= 0:
            return retriever.name, []
        async with semaphore:
            results = await _search_with_timeout(
                retriever,
                query,
                max_results=max_results,
                timeout_s=min(provider_timeout_s, max(0.1, remaining)),
            )
            return retriever.name, results

    tasks = [asyncio.create_task(_run_one(retriever)) for retriever in retrievers]
    if not tasks:
        return []
    done, pending = await asyncio.wait(
        tasks,
        timeout=max(0.1, total_deadline_s - (time.monotonic() - started_at)),
    )
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    outputs: list[tuple[int, str, list[SearchResult]]] = []
    for index, task in enumerate(tasks):
        if task not in done or task.cancelled():
            continue
        try:
            provider_name, results = task.result()
        except Exception:
            continue
        outputs.append((index, provider_name, results))
    outputs.sort(key=lambda item: item[0])
    return [(provider_name, results) for _, provider_name, results in outputs]


async def dispatch_web_search(
    query: str,
    *,
    top_k: int = 5,
    course_id: str | None = None,
    local_sections: list[object] | None = None,
    profile: str | None = None,
    total_timeout_s: float | None = None,
    provider_timeout_s: float | None = None,
) -> list[SearchResult]:
    """Dispatch one query across local and external retrievers.

    ``dispatch_web_search`` is the search layer's scheduler. The public wrapper
    in ``api.py`` keeps most call sites simple; this function exposes knobs used
    by tests, tools, and future specialized workflow paths.

    Args:
        query: Natural-language search query.
        top_k: Final number of fused results to return. This is not the same as
            per-provider result count; each provider is asked for up to
            ``top_k`` candidates and the fused result is capped again.
        course_id: Optional course ID. When present, ``local_rag`` can query
            indexed uploaded materials for that course before web providers.
        local_sections: Optional in-memory local material snippets. This lets a
            workflow pass local context that is not yet in the course vector
            index, while still reusing the same local-first dispatch logic.
        profile: Optional retriever profile name. Profiles live in
            code defaults / optional project settings override and decide which
            retrievers are considered and in what order.
        total_timeout_s: Per-call override for the whole search budget. ``None``
            uses the code-owned default total search budget.
        provider_timeout_s: Per-call override for one provider call. ``None``
            uses the code-owned per-provider timeout.

    Returns:
        Fused, deduplicated ``SearchResult`` objects. Provider failures are
        logged and represented as missing results, not raised exceptions.
    """

    from app.shared.infra.search.factory import get_retrievers_for_course

    total_budget = float(total_timeout_s or DEFAULT_SEARCH_TOTAL_TIMEOUT_S)
    provider_budget = float(provider_timeout_s or DEFAULT_SEARCH_PROVIDER_TIMEOUT_S)
    if not str(query or "").strip() or top_k <= 0:
        return []

    started_at = time.monotonic()
    retrievers = get_retrievers_for_course(
        course_id=course_id,
        local_sections=local_sections,
        profile=profile,
    )
    local_retrievers = [retriever for retriever in retrievers if retriever.name == "local_rag"]
    external_retrievers = [retriever for retriever in retrievers if retriever.name != "local_rag"]
    provider_outputs: list[tuple[str, list[SearchResult]]] = []

    for retriever in local_retrievers:
        remaining = total_budget - (time.monotonic() - started_at)
        if remaining <= 0:
            break
        local_results = await _search_with_timeout(
            retriever,
            query,
            max_results=top_k,
            timeout_s=min(provider_budget, remaining),
        )
        provider_outputs.append((retriever.name, local_results))
        effective_local_count = effective_local_result_count(local_results)
        if effective_local_count >= top_k:
            fused = _fuse_provider_results(
                provider_outputs,
                top_k=top_k,
                fusion_k=max(1, int(DEFAULT_SEARCH_FUSION_K)),
            )
            logger.info(
                "web_search_complete",
                query=query,
                provider=retriever.name,
                result_count=len(fused),
                effective_local_count=effective_local_count,
                elapsed_ms=int((time.monotonic() - started_at) * 1000),
                dispatch_mode="local_sufficient",
            )
            return fused

    remaining = total_budget - (time.monotonic() - started_at)
    if remaining > 0 and external_retrievers:
        if bool(DEFAULT_SEARCH_PARALLEL_RETRIEVERS):
            provider_outputs.extend(
                await _search_retrievers_parallel(
                    external_retrievers,
                    query,
                    max_results=top_k,
                    provider_timeout_s=provider_budget,
                    total_deadline_s=total_budget,
                    started_at=started_at,
                    max_parallel=int(DEFAULT_SEARCH_MAX_PARALLEL_RETRIEVERS),
                )
            )
        else:
            for retriever in external_retrievers:
                remaining = total_budget - (time.monotonic() - started_at)
                if remaining <= 0:
                    logger.info("web_search_budget_exhausted", query=query)
                    break
                provider_outputs.append(
                    (
                        retriever.name,
                        await _search_with_timeout(
                            retriever,
                            query,
                            max_results=top_k,
                            timeout_s=min(provider_budget, remaining),
                        ),
                    )
                )

    fused_results = _fuse_provider_results(
        provider_outputs,
        top_k=top_k,
        fusion_k=max(1, int(DEFAULT_SEARCH_FUSION_K)),
    )
    logger.info(
        "web_search_complete",
        query=query,
        provider_count=len([results for _name, results in provider_outputs if results]),
        result_count=len(fused_results),
        elapsed_ms=int((time.monotonic() - started_at) * 1000),
        dispatch_mode="parallel" if bool(DEFAULT_SEARCH_PARALLEL_RETRIEVERS) else "sequential",
    )
    return fused_results


__all__ = ["dispatch_web_search"]
