"""Evidence probing helpers for the planner graph."""

from __future__ import annotations

import asyncio
import re

from app.shared.infra.search.factory import get_retriever
from app.shared.infra.search.types import SearchResult
from app.shared.infra.settings import get_settings
from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.lib.models import EvidenceBrief, EvidenceSource, PlannerBrief

_CJK_RE = re.compile(r"[\u3400-\u9fff]{2,16}")


def source_preview(value: str, *, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def triage_sources(
    results: list[SearchResult],
    *,
    limit: int,
    source_type: str,
) -> list[EvidenceSource]:
    selected: list[EvidenceSource] = []
    seen: set[str] = set()
    for result in results:
        key = result.url or f"{result.title}::{result.snippet[:80]}"
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(
            EvidenceSource(
                title=result.title or result.url,
                url=result.url,
                source_type=source_type,
                reason="与本轮学习目标和检索词相关。",
                preview=source_preview(result.snippet),
                opened=False,
            )
        )
        if len(selected) >= limit:
            break
    return selected


async def safe_search(
    retriever_name: str,
    *,
    query: str,
    subject: str,
    local_sections: list[object],
    max_results: int = 2,
) -> list[SearchResult]:
    settings = get_settings()
    try:
        retriever = get_retriever(
            retriever_name,
            subject=subject if retriever_name in {"local_rag", "rag"} else None,
            local_sections=local_sections if retriever_name in {"local_rag", "rag"} else None,
        )
        return await asyncio.wait_for(
            retriever.traced_search(query, max_results=max_results),
            timeout=max(0.1, float(settings.search.provider_timeout_s)),
        )
    except Exception:
        return []


def fallback_probe_queries(
    material_context: DigestMaterialContext,
    *,
    planner_brief: PlannerBrief,
) -> list[str]:
    raw_candidates = [
        *material_context.learning_domain_profile.key_topics[:6],
        *material_context.material_hints.chapter_candidates[:6],
        *planner_brief.focus_points[:4],
        *planner_brief.outline_items[:4],
    ]
    queries: list[str] = []
    seen: set[str] = set()
    for item in raw_candidates:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        queries.append(f"{text} 核心概念 学习重点")
        if len(queries) >= 4:
            break
    return queries


def merge_opened_sources(
    *,
    selected_sources: list[EvidenceSource],
    opened_sources: list[EvidenceSource],
) -> list[EvidenceSource]:
    merged: list[EvidenceSource] = []
    opened_by_key = {
        (source.url or source.title or "").casefold(): source
        for source in opened_sources
        if source.url or source.title
    }
    seen: set[str] = set()
    for source in [*opened_sources, *selected_sources]:
        key = (source.url or source.title or source.preview).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(opened_by_key.get(key, source))
    return merged


def collect_core_concepts(
    *,
    material_context: DigestMaterialContext,
    local_results: list[SearchResult],
    sources: list[EvidenceSource],
) -> list[str]:
    candidates: list[str] = []
    candidates.extend(material_context.learning_domain_profile.key_topics)
    candidates.extend(material_context.material_hints.chapter_candidates)
    for item in local_results[:8]:
        candidates.append(item.title)
        candidates.extend(match.group(0) for match in _CJK_RE.finditer(item.snippet))
    for source in sources[:8]:
        candidates.append(source.title)
        candidates.extend(match.group(0) for match in _CJK_RE.finditer(source.preview))

    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        text = str(item or "").strip()
        if not text or len(text) > 20:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
        if len(deduped) >= 10:
            break
    return deduped


def build_evidence_brief(
    *,
    material_context: DigestMaterialContext,
    planner_brief: PlannerBrief,
    queries: list[str],
    selected_sources: list[EvidenceSource],
    opened_sources: list[EvidenceSource],
    local_results: list[SearchResult],
    web_results: list[SearchResult],
) -> EvidenceBrief:
    sources = merge_opened_sources(selected_sources=selected_sources, opened_sources=opened_sources)
    source_titles = [source.title for source in sources[:5] if source.title]
    core_concepts = collect_core_concepts(
        material_context=material_context,
        local_results=local_results,
        sources=sources,
    )
    summary = (
        "已读取的规划证据："
        + ("；".join(source_titles) if source_titles else "暂无可用证据，使用资料画像和用户目标规划。")
        + (f"。重点概念包括：{'、'.join(core_concepts[:6])}" if core_concepts else "")
    )
    chapter_hints = [
        f"{chapter}：结合 {source_titles[index % len(source_titles)]} 校准章节边界。"
        for index, chapter in enumerate(planner_brief.outline_items[:4])
        if source_titles
    ]
    return EvidenceBrief(
        queries=queries,
        sources=sources,
        summary=summary,
        core_concepts=core_concepts,
        chapter_hints=chapter_hints,
        gap_notes=[] if sources else ["当前证据不足，最终方案将更多依赖资料画像和用户目标。"],
        local_hit_count=len(local_results),
        web_hit_count=len(web_results),
    )


__all__ = [
    "build_evidence_brief",
    "fallback_probe_queries",
    "safe_search",
    "source_preview",
    "triage_sources",
]
