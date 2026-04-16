"""Evidence probing helpers for the planner graph."""

from __future__ import annotations

import asyncio
import re

from app.shared.infra.search.factory import get_retriever
from app.shared.infra.search.types import SearchResult
from app.shared.infra.settings import get_settings
from app.workflows.digest.common.models import DigestMaterialContext
from app.workflows.digest.planner.lib.research_probe import (
    ChapterEvidenceHint,
    EvidenceBrief,
    PlanSketch,
    PlannerOpenedSource,
    PlannerSelectedSource,
)

_CJK_RE = re.compile(r"[\u3400-\u9fff]{2,16}")


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


def fallback_local_queries(
    material_context: DigestMaterialContext,
    *,
    plan_sketch: PlanSketch,
) -> list[str]:
    raw_candidates = [
        *material_context.learning_domain_profile.key_topics[:6],
        *material_context.material_hints.chapter_candidates[:6],
        *[str(item).strip() for item in list(plan_sketch.provisional_chapters or [])[:4]],
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
        queries.append(text)
        if len(queries) >= 4:
            break
    return queries


def source_preview(value: str, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def collect_core_concepts(
    *,
    material_context: DigestMaterialContext,
    local_results: list[SearchResult],
    opened_sources: list[PlannerOpenedSource],
) -> list[str]:
    candidates: list[str] = []
    candidates.extend(material_context.learning_domain_profile.key_topics)
    candidates.extend(material_context.material_hints.chapter_candidates)
    for item in local_results[:8]:
        candidates.append(item.title)
        candidates.extend(match.group(0) for match in _CJK_RE.finditer(item.snippet))
    for source in opened_sources[:6]:
        candidates.append(source.title)
        candidates.extend(match.group(0) for match in _CJK_RE.finditer(source.content_preview))

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
    plan_sketch: PlanSketch,
    selected_sources: list[PlannerSelectedSource],
    opened_sources: list[PlannerOpenedSource],
    local_results: list[SearchResult],
    web_results: list[SearchResult],
    curator_meta: dict[str, object],
) -> EvidenceBrief:
    topic_titles = [source.title for source in opened_sources[:5] if source.title]
    core_concepts = collect_core_concepts(
        material_context=material_context,
        local_results=local_results,
        opened_sources=opened_sources,
    )
    concept_briefing = (
        "已读取的规划证据："
        + ("；".join(topic_titles) if topic_titles else "暂无可用证据，使用资料画像和用户目标规划。")
        + (f"。重点概念包括：{'、'.join(core_concepts[:6])}" if core_concepts else "")
    )
    return EvidenceBrief(
        selected_sources=selected_sources,
        opened_sources=opened_sources,
        concept_briefing=concept_briefing,
        core_concepts=core_concepts,
        chapter_evidence_hints=[
            ChapterEvidenceHint(
                chapter_hint=(
                    plan_sketch.provisional_chapters[index]
                    if index < len(plan_sketch.provisional_chapters)
                    else title
                ),
                evidence_summary=f"重点覆盖 {title} 及相关概念，避免只罗列术语。",
                source_titles=topic_titles[:3],
            )
            for index, title in enumerate(topic_titles[:4])
        ],
        gap_notes=[] if opened_sources else ["当前证据不足，最终方案将更多依赖资料画像和用户目标。"],
        source_quality_summary={
            "local": sum(1 for source in selected_sources if source.source_type == "local"),
            "web": sum(1 for source in selected_sources if source.source_type == "web"),
            "trusted": int((curator_meta or {}).get("trusted_source_count", 0) or 0),
            "unique_domains": int((curator_meta or {}).get("unique_domain_count", 0) or 0),
        },
        local_hit_count=len(local_results),
        web_hit_count=len(web_results),
    )


__all__ = [
    "build_evidence_brief",
    "fallback_local_queries",
    "safe_search",
    "source_preview",
]
