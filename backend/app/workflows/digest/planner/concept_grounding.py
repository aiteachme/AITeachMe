"""Lightweight concept grounding for planner outline quality."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.search.factory import get_retriever
from app.shared.infra.search.types import SearchResult
from app.teaching.runtime_config import get_teaching_runtime_config
from app.workflows.common.runtime_stats import tracked_step
from app.workflows.digest.planner.models import _resolve_subject_display_name
from app.workflows.digest.shared.models import SharedInputs

logger = structlog.get_logger(__name__)

_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_TITLE_SPLIT_RE = re.compile(r"\s*[-—|｜:：]\s*")
_SPACE_SPLIT_RE = re.compile(r"\s+")


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
    if callable(parse_retrievers):
        return [
            name
            for name in parse_retrievers(include_local_rag=False, include_fallback=True)
            if name not in {"local_rag", "rag"}
        ]

    primary = str(getattr(settings, "web_search_retriever", "duckduckgo") or "duckduckgo").strip().lower()
    ordered = [primary] if primary else []
    if primary not in {"duckduckgo", ""}:
        ordered.append("duckduckgo")
    return [name for name in ordered if name and name not in {"local_rag", "rag"}]


async def _safe_search(
    retriever_name: str,
    *,
    query: str,
    subject: str,
    local_sections: list[Any],
    max_results: int,
) -> list[SearchResult]:
    try:
        retriever = get_retriever(
            retriever_name,
            subject=subject if retriever_name in {"local_rag", "rag"} else None,
            local_sections=local_sections if retriever_name in {"local_rag", "rag"} else None,
        )
        return await retriever.traced_search(query, max_results=max_results)
    except Exception as exc:
        logger.warning(
            "planner_concept_search_failed",
            retriever=retriever_name,
            query=query,
            error=str(exc),
        )
        return []


def _format_concept_briefing(
    *,
    queries: list[str],
    evidence: list[PlannerConceptEvidence],
    topic_hints: list[str],
) -> str:
    if not evidence:
        return "暂无额外概念检索结果，可先依据资料主题、章节提示和用户目标规划。"

    grouped: dict[str, list[PlannerConceptEvidence]] = {query: [] for query in queries}
    for item in evidence:
        grouped.setdefault(item.query, []).append(item)

    lines = ["快速概念检索锚点："]
    for query in queries:
        hits = grouped.get(query) or []
        if not hits:
            continue
        lines.append(f"- 检索词：{query}")
        for hit in hits[:3]:
            lane_label = "本地" if hit.lane == "local" else "外部"
            lines.append(
                f"  - [{lane_label}/{hit.source}] {hit.title}：{_truncate_text(hit.snippet, limit=88)}"
            )
    if topic_hints:
        lines.append(f"建议优先覆盖的概念锚点：{'、'.join(topic_hints[:8])}")
    return "\n".join(lines)


async def collect_planner_concept_briefing(
    *,
    subject: str,
    user_goal: str,
    shared_inputs: SharedInputs,
    latest_plan: dict[str, Any] | None = None,
) -> PlannerConceptBriefing:
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
    async with tracked_step(
        None,
        name="local_retrieval",
        kind="substep",
        trace_run_type="retriever",
        trace_metadata={"retriever": "local_rag"},
        trace_inputs={"query_count": len(queries)},
    ) as step:
        local_tasks = [
            _safe_search(
                "local_rag",
                query=query,
                subject=subject,
                local_sections=local_sections,
                max_results=2,
            )
            for query in queries
        ]
        local_results = await asyncio.gather(*local_tasks)
        step.set_outputs(
            query_count=len(queries),
            result_count=sum(len(items) for items in local_results),
        )

    external_queries = [f"{query} 百科 定义" for query in queries[:2]]
    external_retrievers = _resolve_external_retriever_names()
    external_results: list[list[SearchResult]] = [[] for _ in external_queries]
    if external_queries and external_retrievers:
        async with tracked_step(
            None,
            name="web_retrieval",
            kind="substep",
            trace_run_type="retriever",
            trace_metadata={"retriever_candidates": external_retrievers},
            trace_inputs={"query_count": len(external_queries)},
        ) as step:
            for index, query in enumerate(external_queries):
                hits: list[SearchResult] = []
                for retriever_name in external_retrievers:
                    hits = await _safe_search(
                        retriever_name,
                        query=query,
                        subject=subject,
                        local_sections=local_sections,
                        max_results=2,
                    )
                    if hits:
                        break
                external_results[index] = hits
            step.set_outputs(
                query_count=len(external_queries),
                result_count=sum(len(items) for items in external_results),
            )

    display_subject = _resolve_subject_display_name(
        subject,
        shared_inputs=shared_inputs,
        user_goal=user_goal,
    )
    evidence: list[PlannerConceptEvidence] = []
    topic_candidates: list[str] = []
    local_hit_count = 0
    web_hit_count = 0

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
            web_hit_count += 1
            evidence.append(
                PlannerConceptEvidence(
                    query=query,
                    title=_clean_text(hit.title) or _truncate_text(hit.url, limit=36),
                    snippet=_clean_text(hit.snippet),
                    url=hit.url,
                    source=hit.source or "duckduckgo",
                    lane="web",
                )
            )
            topic = _extract_result_topic(hit.title, display_subject=display_subject)
            if topic:
                topic_candidates.append(topic)

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
    )


__all__ = [
    "PlannerConceptBriefing",
    "PlannerConceptEvidence",
    "build_planner_concept_queries",
    "collect_planner_concept_briefing",
]
