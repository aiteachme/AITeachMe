"""Lightweight concept grounding for planner outline quality."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

import structlog
from langsmith import traceable

from app.shared.infra.config import get_settings
from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.search import SourceCurator
from app.shared.infra.search.factory import get_retriever
from app.shared.infra.search.types import ScrapedPage, SearchResult
from app.shared.infra.tools.builtin.web_reading import read_urls
from app.workflows.digest._shared.runtime_config import get_teaching_runtime_config
from app.workflows.digest.planner.lib.plans import _resolve_subject_display_name
from app.workflows.digest.shared.contracts import resolve_planner_retrieval_profile
from app.workflows.digest.shared.models import SharedInputs

logger = structlog.get_logger(__name__)

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_TITLE_SPLIT_RE = re.compile(r"\s*[-—|｜:：]\s*")
_SPACE_SPLIT_RE = re.compile(r"\s+")
_PLANNER_WEB_READ_LIMIT = 2
_PLANNER_PAGE_PREVIEW_CHARS = 180


@dataclass(slots=True)
class PlannerConceptEvidence:
    query: str
    title: str
    snippet: str
    url: str
    source: str
    lane: str


@dataclass(slots=True)
class PlannerConceptBriefing:
    queries: list[str] = field(default_factory=list)
    topic_hints: list[str] = field(default_factory=list)
    briefing: str = ""
    evidence: list[PlannerConceptEvidence] = field(default_factory=list)
    local_hit_count: int = 0
    web_hit_count: int = 0
    web_read_count: int = 0


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _has_cjk(text: str) -> bool:
    return bool(_CJK_RE.search(text))


def _dedupe_strings(items: list[str], *, limit: int | None = None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _clean_text(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
        if limit is not None and len(deduped) >= limit:
            break
    return deduped


def _truncate_text(value: str, *, limit: int) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip("，。；：,. ") + "…"


def _build_page_preview(page: ScrapedPage, *, fallback: str = "") -> str:
    if page.success and page.content.strip():
        return _truncate_text(page.content, limit=_PLANNER_PAGE_PREVIEW_CHARS)
    return _truncate_text(fallback, limit=_PLANNER_PAGE_PREVIEW_CHARS)


def _extract_topic_seed_from_goal(user_goal: str) -> str:
    goal = _clean_text(user_goal)
    if not goal:
        return ""
    head = re.split(r"[，。；：,.!?！？\n]", goal, maxsplit=1)[0].strip()
    if not head or len(head) > 26:
        return ""
    return head


def _extract_result_topic(title: str, *, display_subject: str) -> str:
    cleaned = _clean_text(title)
    if not cleaned:
        return ""
    head = _TITLE_SPLIT_RE.split(cleaned, maxsplit=1)[0].strip()
    if not head:
        return ""
    if head == display_subject and _has_cjk(head):
        return head
    if 2 <= len(head) <= 20 and _has_cjk(head):
        return head
    return ""


def build_planner_concept_queries(
    *,
    subject: str,
    user_goal: str,
    shared_inputs: SharedInputs,
    latest_plan: dict[str, Any] | None = None,
) -> list[str]:
    display_subject = _resolve_subject_display_name(
        subject,
        shared_inputs=shared_inputs,
        user_goal=user_goal,
    )
    latest_plan = latest_plan or {}
    chapter_titles = [
        _clean_text(item.get("title"))
        for item in list(latest_plan.get("chapter_plan") or [])
        if isinstance(item, dict)
    ]
    topic_candidates = _dedupe_strings(
        [
            display_subject,
            *_clean_and_filter_topics(shared_inputs.subject_profile.key_topics),
            *_clean_and_filter_topics(shared_inputs.fast_hints.chapter_candidates),
            *_clean_and_filter_topics(chapter_titles),
            _extract_topic_seed_from_goal(user_goal),
        ],
        limit=6,
    )
    if not topic_candidates:
        topic_candidates = [display_subject or "当前主题"]

    queries: list[str] = [f"{display_subject} 基础概念 知识框架".strip()]
    for topic in topic_candidates:
        if topic == display_subject:
            continue
        queries.append(f"{topic} 定义 关键性质")
        if len(queries) >= 4:
            break

    if len(queries) < 3:
        queries.append(f"{display_subject} 应用场景 常见方法".strip())
    return _dedupe_strings(queries, limit=4)


def _clean_and_filter_topics(items: list[Any]) -> list[str]:
    return [
        text
        for text in (_clean_text(item) for item in items)
        if text and _has_cjk(text) and len(text) <= 24
    ]


def _resolve_external_retriever_names() -> list[str]:
    settings = get_settings()
    if not get_teaching_runtime_config().planner.allow_external_search:
        return []
    parse_retrievers = getattr(settings, "parse_retrievers", None)
    profile = resolve_planner_retrieval_profile()
    if callable(parse_retrievers):
        return [
            name
            for name in parse_retrievers(profile=profile, include_local_rag=False, include_fallback=True)
            if name not in {"local_rag", "rag"}
        ]
    return ["searxng", "bocha", "duckduckgo"]


async def _safe_search(
    retriever_name: str,
    *,
    query: str,
    subject: str,
    local_sections: list[Any],
    max_results: int,
    timeout_s: float,
) -> list[SearchResult]:
    try:
        retriever = get_retriever(
            retriever_name,
            subject=subject if retriever_name in {"local_rag", "rag"} else None,
            local_sections=local_sections if retriever_name in {"local_rag", "rag"} else None,
        )
        return await asyncio.wait_for(
            retriever.traced_search(query, max_results=max_results),
            timeout=max(0.1, timeout_s),
        )
    except TimeoutError:
        logger.warning(
            "planner_concept_search_timeout",
            retriever=retriever_name,
            query=query,
            timeout_s=timeout_s,
        )
        return []
    except Exception as exc:
        logger.warning(
            "planner_concept_search_failed",
            retriever=retriever_name,
            query=query,
            error=str(exc),
        )
        return []


@traceable(name="planner.grounding.query_batch", run_type="chain")
async def _run_planner_query_batch(
    *,
    query: str,
    retriever_names: list[str],
    subject: str,
    local_sections: list[Any],
    max_results: int,
    timeout_s: float,
) -> list[list[SearchResult]]:
    return await asyncio.gather(
        *(
            _safe_search(
                retriever_name,
                query=query,
                subject=subject,
                local_sections=local_sections,
                max_results=max_results,
                timeout_s=timeout_s,
            )
            for retriever_name in retriever_names
        )
    )


async def _prioritize_external_results(
    *,
    subject: str,
    query: str,
    results: list[list[SearchResult]],
) -> list[SearchResult]:
    flattened: list[SearchResult] = []
    seen: set[str] = set()
    for hits in results:
        for hit in hits:
            key = _clean_text(hit.url) or f"{_clean_text(hit.title)}::{_clean_text(hit.snippet)[:120]}"
            if not key or key in seen:
                continue
            seen.add(key)
            flattened.append(hit)
    if not flattened:
        return []

    curator = SourceCurator(TracedExecutionContext(subject=subject))
    curated, _ = await curator.curate_sources(
        query=query,
        sources=flattened,
        max_results=_PLANNER_WEB_READ_LIMIT,
    )
    return curated


async def _read_external_pages(results: list[SearchResult]) -> dict[str, ScrapedPage]:
    urls: list[str] = []
    seen_urls: set[str] = set()
    for hit in results:
        url = _clean_text(hit.url)
        if not url or url.startswith("local://") or url in seen_urls:
            continue
        seen_urls.add(url)
        urls.append(url)
        if len(urls) >= _PLANNER_WEB_READ_LIMIT:
            break

    if not urls:
        return {}

    pages = await read_urls(urls)
    return {page.url: page for page in pages if page.url}


def _format_concept_briefing(
    *,
    queries: list[str],
    evidence: list[PlannerConceptEvidence],
    topic_hints: list[str],
) -> str:
    lines = ["快速概念检索锚点："]
    if queries:
        lines.append(f"- 本轮概念校准检索词：{'；'.join(queries[:4])}")
    if topic_hints:
        lines.append(f"- 建议优先覆盖的概念锚点：{'、'.join(topic_hints[:8])}")
    if evidence:
        local_count = sum(1 for item in evidence if item.lane == "local")
        web_count = sum(1 for item in evidence if item.lane != "local")
        lines.append(f"- 已完成概念校准：本地资料 {local_count} 条，外部校验 {web_count} 条。")
        lines.append("- 注意：外部网页仅用于校验概念范围，不能把网站名、作者名、网页标题写进研究任务。")
    if len(lines) == 1:
        return "暂无额外概念检索结果，可先依据资料主题、章节提示和用户目标规划。"
    return "\n".join(lines)


async def collect_planner_concept_briefing(
    *,
    subject: str,
    user_goal: str,
    shared_inputs: SharedInputs,
    latest_plan: dict[str, Any] | None = None,
) -> PlannerConceptBriefing:
    settings = get_settings()
    queries = build_planner_concept_queries(
        subject=subject,
        user_goal=user_goal,
        shared_inputs=shared_inputs,
        latest_plan=latest_plan,
    )
    if not queries:
        return PlannerConceptBriefing(
            briefing="暂无可用的概念检索词，将直接依据资料与目标规划。",
        )

    local_sections = list(shared_inputs.section_packets)
    total_budget = max(1.0, float(getattr(settings, "planner_grounding_timeout_s", 10.0)))
    provider_budget = max(0.5, float(getattr(settings, "search_provider_timeout_s", 6.0)))
    started_at = time.monotonic()

    local_started_at = perf_counter()
    local_results_nested = await asyncio.gather(
        *(
            _run_planner_query_batch(
                query=query,
                retriever_names=["local_rag"],
                subject=subject,
                local_sections=local_sections,
                max_results=2,
                timeout_s=min(provider_budget, total_budget),
            )
            for query in queries
        )
    )
    local_results = [items[0] if items else [] for items in local_results_nested]
    logger.info(
        "planner_concept_local_retrieval_completed",
        subject=subject,
        query_count=len(queries),
        result_count=sum(len(items) for items in local_results),
        elapsed_ms=int((perf_counter() - local_started_at) * 1000),
    )

    external_queries = _dedupe_strings(queries[:2], limit=2)
    external_retrievers = _resolve_external_retriever_names()
    external_results: list[list[SearchResult]] = [[] for _ in external_queries]
    if external_queries and external_retrievers:
        web_started_at = perf_counter()
        for index, query in enumerate(external_queries):
            hits: list[SearchResult] = []
            remaining = total_budget - (time.monotonic() - started_at)
            if remaining <= 0:
                logger.info("planner_concept_budget_exhausted", query=query, result_count=sum(len(x) for x in external_results))
                break
            provider_hits = await _run_planner_query_batch(
                query=query,
                retriever_names=external_retrievers,
                subject=subject,
                local_sections=local_sections,
                max_results=2,
                timeout_s=min(provider_budget, remaining),
            )
            for batch in provider_hits:
                if batch:
                    hits = batch
                    break
            external_results[index] = hits
        logger.info(
            "planner_concept_web_retrieval_completed",
            subject=subject,
            query_count=len(external_queries),
            result_count=sum(len(items) for items in external_results),
            elapsed_ms=int((perf_counter() - web_started_at) * 1000),
        )
    external_results_for_read = await _prioritize_external_results(
        subject=subject,
        query=" ".join(external_queries),
        results=external_results,
    )
    external_pages = await _read_external_pages(external_results_for_read)

    display_subject = _resolve_subject_display_name(
        subject,
        shared_inputs=shared_inputs,
        user_goal=user_goal,
    )
    evidence: list[PlannerConceptEvidence] = []
    topic_candidates: list[str] = []
    local_hit_count = 0
    web_hit_count = 0
    web_read_count = 0

    for query, hits in zip(queries, local_results):
        for hit in hits[:2]:
            if not hit.title and not hit.snippet:
                continue
            local_hit_count += 1
            evidence.append(
                PlannerConceptEvidence(
                    query=query,
                    title=_clean_text(hit.title) or _truncate_text(hit.url, limit=36),
                    snippet=_clean_text(hit.snippet),
                    url=hit.url,
                    source=hit.source or "local_rag",
                    lane="local",
                )
            )
            topic = _extract_result_topic(hit.title, display_subject=display_subject)
            if topic:
                topic_candidates.append(topic)

    for query, hits in zip(queries[:2], external_results):
        for hit in hits[:2]:
            if not hit.title and not hit.snippet:
                continue
            page = external_pages.get(hit.url)
            web_hit_count += 1
            if page is not None and page.success and page.content.strip():
                web_read_count += 1
            evidence.append(
                PlannerConceptEvidence(
                    query=query,
                    title=_clean_text(page.title if page is not None else "") or _clean_text(hit.title) or _truncate_text(hit.url, limit=36),
                    snippet=_build_page_preview(page, fallback=hit.snippet) if page is not None else _truncate_text(hit.snippet, limit=_PLANNER_PAGE_PREVIEW_CHARS),
                    url=hit.url,
                    source=hit.source or "duckduckgo",
                    lane="web",
                )
            )
    topic_hints = _dedupe_strings(
        [
            *_clean_and_filter_topics(shared_inputs.subject_profile.key_topics),
            *_clean_and_filter_topics(shared_inputs.fast_hints.chapter_candidates),
            *topic_candidates,
        ],
        limit=8,
    )
    return PlannerConceptBriefing(
        queries=queries,
        topic_hints=topic_hints,
        briefing=_format_concept_briefing(
            queries=queries,
            evidence=evidence,
            topic_hints=topic_hints,
        ),
        evidence=evidence,
        local_hit_count=local_hit_count,
        web_hit_count=web_hit_count,
        web_read_count=web_read_count,
    )


__all__ = [
    "PlannerConceptBriefing",
    "PlannerConceptEvidence",
    "build_planner_concept_queries",
    "collect_planner_concept_briefing",
]
