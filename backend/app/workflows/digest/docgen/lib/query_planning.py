"""Workflow-local query planning helpers for DocGen research."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field

from app.shared.infra.llm_support import acompletion_with_fallback, run_llm_tasks
from app.workflows.digest.docgen.lib.model_policy import DocGenModelStep, docgen_completion_kwargs_with_metadata
from app.workflows.digest.docgen.prompts.generation import (
    build_docgen_gap_query_messages,
    build_docgen_sub_query_messages,
)

EDUCATION_SITE_FILTERS: dict[str, list[str]] = {
    "zh": [],
    "university": [
        "site:icourse163.org",
        "site:xuetangx.com",
        "site:ocw.mit.edu",
    ],
    "exam": [
        "site:kaoyan.com",
        "site:233.com",
        "真题 解析",
    ],
    "knowledge": [],
}
QUERY_CONTEXT_ITEM_COUNT_BUDGET = 6
QUERY_CONTEXT_ITEM_CHAR_BUDGET = 180
SITE_FILTER_COMPATIBLE_RETRIEVERS = {
    "baidu_ai_search",
    "bing",
    "bocha",
    "brave",
    "duckduckgo",
    "exa",
    "google_cse",
    "jina_search",
    "mcp_search",
    "openrouter_search",
    "perplexity",
    "searchapi",
    "searxng",
    "serpapi",
    "serper",
    "tavily",
}

class ResearchSubQueryPlan(BaseModel):
    queries: list[str] = Field(default_factory=list, description="围绕当前章节主题拆解出的研究子查询")


def dedupe_queries(queries: Sequence[str], *, limit: int | None = None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw_query in queries:
        query = " ".join(str(raw_query or "").split()).strip()
        if not query or query in seen:
            continue
        seen.add(query)
        cleaned.append(query)
        if limit is not None and len(cleaned) >= limit:
            break
    return cleaned


def enrich_queries_for_education(
    queries: Sequence[str],
    *,
    domain: str = "zh",
    max_site_filters_per_query: int = 1,
) -> list[str]:
    normalized_queries = dedupe_queries(list(queries))
    filters = EDUCATION_SITE_FILTERS.get(domain, [])[: max(0, max_site_filters_per_query)]
    enriched: list[str] = []
    seen: set[str] = set()
    for query in normalized_queries:
        for candidate in [query, *[f"{query} {site_filter}".strip() for site_filter in filters]]:
            if candidate in seen:
                continue
            seen.add(candidate)
            enriched.append(candidate)
    return enriched


def enrich_queries_for_retriever(
    queries: Sequence[str],
    *,
    domain: str = "zh",
    retriever_name: str = "",
    max_site_filters_per_query: int = 1,
) -> list[str]:
    """Expand search queries only for retrievers that understand web operators."""

    normalized_name = str(retriever_name or "").strip().lower()
    if normalized_name not in SITE_FILTER_COMPATIBLE_RETRIEVERS:
        return dedupe_queries(list(queries))
    return enrich_queries_for_education(
        queries,
        domain=domain,
        max_site_filters_per_query=max_site_filters_per_query,
    )


def build_research_focus_text(
    *,
    title: str,
    objective: str = "",
    required_elements: list[str] | None = None,
    digest_mode: str = "",
) -> str:
    parts: list[str] = []
    normalized_title = str(title or "").strip()
    normalized_objective = str(objective or "").strip()
    normalized_required = [str(item).strip() for item in required_elements or [] if str(item).strip()]
    normalized_mode = str(digest_mode or "").strip()

    if normalized_title:
        parts.append(f"章节：{normalized_title}")
    if normalized_objective:
        parts.append(f"目标：{normalized_objective}")
    if normalized_required:
        parts.append("必须覆盖：" + "、".join(normalized_required))
    if normalized_mode:
        parts.append(f"模式：{normalized_mode}")
    return " | ".join(parts).strip()


def _serialize_query_context(context: Sequence[str | Mapping[str, Any]] | None) -> list[dict[str, str]]:
    serialized: list[dict[str, str]] = []
    for item in list(context or [])[:QUERY_CONTEXT_ITEM_COUNT_BUDGET]:
        if isinstance(item, Mapping):
            title = str(item.get("title") or item.get("label") or item.get("name") or "").strip()
            detail = str(item.get("detail") or item.get("value") or item.get("objective") or "").strip()
            if len(detail) > QUERY_CONTEXT_ITEM_CHAR_BUDGET:
                detail = detail[:QUERY_CONTEXT_ITEM_CHAR_BUDGET].rstrip() + "..."
            text = " | ".join(part for part in [title, detail] if part).strip()
        else:
            text = str(item or "").strip()
            if len(text) > QUERY_CONTEXT_ITEM_CHAR_BUDGET:
                text = text[:QUERY_CONTEXT_ITEM_CHAR_BUDGET].rstrip() + "..."
        if not text:
            continue
        serialized.append({"text": text})
    return serialized


async def generate_sub_queries(
    query: str,
    *,
    context: Sequence[str | Mapping[str, Any]] | None = None,
    max_queries: int = 3,
    domain: str = "education",
    llm_caller: Callable[..., Awaitable[Any]] | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> list[str]:
    """Generate research sub-queries with an LLM."""

    normalized_query = " ".join(str(query or "").split()).strip()
    if not normalized_query:
        return []

    safe_max_queries = max(1, int(max_queries or 1))
    serialized_context = _serialize_query_context(context)
    caller = llm_caller or acompletion_with_fallback

    async def _run_sub_query_plan(_: object) -> object:
        return await caller(
            build_docgen_sub_query_messages(
                query=normalized_query,
                context_summary=serialized_context,
                max_queries=safe_max_queries,
                domain=domain,
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.QUERY_PLANNING,
                extra_metadata=extra_metadata,
                query_tool="generate_sub_queries",
                query_domain=domain,
            ),
            response_model=ResearchSubQueryPlan,
        )

    (response,) = await run_llm_tasks([None], _run_sub_query_plan, max_concurrent=1)

    if isinstance(response, ResearchSubQueryPlan):
        raw_queries = response.queries
    elif hasattr(response, "queries"):
        raw_queries = list(getattr(response, "queries") or [])
    elif isinstance(response, Mapping):
        raw_queries = list(response.get("queries") or [])
    else:
        raw_queries = []

    cleaned = [
        item
        for item in dedupe_queries([str(raw) for raw in raw_queries], limit=safe_max_queries)
        if item and item != normalized_query
    ]
    return cleaned


async def generate_gap_queries(
    dense_context: str,
    *,
    required_elements: list[str] | None = None,
    max_queries: int = 2,
    domain: str = "education",
    llm_caller: Callable[..., Awaitable[Any]] | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
) -> list[str]:
    """Analyze the current dense context and generate new queries to fill knowledge gaps."""
    if not str(dense_context or "").strip():
        return []

    caller = llm_caller or acompletion_with_fallback

    async def _run_gap_query_plan(_: object) -> object:
        return await caller(
            build_docgen_gap_query_messages(
                dense_context=dense_context,
                required_elements=list(required_elements or []),
                max_queries=int(max_queries or 2),
                domain=domain,
            ),
            **docgen_completion_kwargs_with_metadata(
                DocGenModelStep.QUERY_PLANNING,
                extra_metadata=extra_metadata,
                query_tool="generate_gap_queries",
                query_domain=domain,
            ),
            response_model=ResearchSubQueryPlan,
        )

    (response,) = await run_llm_tasks([None], _run_gap_query_plan, max_concurrent=1)

    if isinstance(response, ResearchSubQueryPlan):
        raw_queries = response.queries
    elif hasattr(response, "queries"):
        raw_queries = list(getattr(response, "queries") or [])
    elif isinstance(response, Mapping):
        raw_queries = list(response.get("queries") or [])
    else:
        raw_queries = []

    cleaned = [
        item
        for item in dedupe_queries([str(raw) for raw in raw_queries], limit=int(max_queries or 2))
        if item
    ]
    return cleaned


__all__ = [
    "EDUCATION_SITE_FILTERS",
    "QUERY_CONTEXT_ITEM_CHAR_BUDGET",
    "QUERY_CONTEXT_ITEM_COUNT_BUDGET",
    "ResearchSubQueryPlan",
    "build_research_focus_text",
    "dedupe_queries",
    "enrich_queries_for_education",
    "enrich_queries_for_retriever",
    "generate_sub_queries",
    "generate_gap_queries",
    "SITE_FILTER_COMPATIBLE_RETRIEVERS",
]
