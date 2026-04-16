"""Probe local/web evidence for Planner V3."""

from __future__ import annotations

import asyncio
import re

import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.search import SourceCurator
from app.shared.infra.search.factory import get_retriever
from app.shared.infra.search.types import SearchResult
from app.shared.infra.tools.builtin.web_reading import read_urls
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.lib.research_probe import (
    ChapterEvidenceHint,
    EvidenceBrief,
    LearningIntentProfile,
    PlanSketch,
    PlannerOpenedSource,
    PlannerSelectedSource,
    ResearchProbePlan,
)
from app.workflows.digest.planner.lib.source_triage import rule_based_source_triage
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)

async def _safe_search(retriever_name: str, *, query: str, subject: str, local_sections: list[object]) -> list[SearchResult]:
    settings = get_settings()
    try:
        retriever = get_retriever(
            retriever_name,
            subject=subject if retriever_name in {"local_rag", "rag"} else None,
            local_sections=local_sections if retriever_name in {"local_rag", "rag"} else None,
        )
        return await asyncio.wait_for(
            retriever.traced_search(query, max_results=2),
            timeout=max(0.1, float(settings.search_provider_timeout_s)),
        )
    except Exception:
        return []


def _fallback_local_queries(state: BuildPlannerState) -> list[str]:
    material_context = state["material_context"]
    raw_candidates = [
        *material_context.learning_domain_profile.key_topics[:6],
        *material_context.material_hints.chapter_candidates[:6],
        *[str(item).strip() for item in list((state.get("plan_sketch") or {}).get("provisional_chapters") or [])[:4]],
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


def _source_preview(value: str, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


_CJK_RE = re.compile(r"[\u3400-\u9fff]{2,16}")


def _collect_core_concepts(*, state: BuildPlannerState, local_results: list[SearchResult], opened_sources: list[PlannerOpenedSource]) -> list[str]:
    material_context = state["material_context"]
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


def build_probe_evidence_node(*, context: WorkflowContext):
    async def probe_evidence_node(state: BuildPlannerState) -> dict:
        material_context = state["material_context"]
        intent = LearningIntentProfile.model_validate(state.get("learning_intent_profile") or {})
        probe_plan = ResearchProbePlan.model_validate(state.get("research_probe_plan") or intent.research_probe_plan.model_dump())
        plan_sketch = PlanSketch.model_validate(state.get("plan_sketch") or {})
        local_sections = list(material_context.material_sections)
        logger.info(
            "planner_probe_started",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state["subject"],
            local_sections_count=len(local_sections),
            local_query_count=len(probe_plan.local_queries),
            web_query_count=len(probe_plan.web_queries),
        )
        await emit_planner_event(
            state,
            event="planner.probe.started",
            detail="正在检索本地资料和少量外部概念来源...",
            payload={
                "local_query_count": len(probe_plan.local_queries),
                "web_query_count": len(probe_plan.web_queries),
                "local_sections_count": len(local_sections),
                "local_queries": [query.query for query in probe_plan.local_queries[:4]],
                "web_queries": [query.query for query in probe_plan.web_queries[:3]],
            },
        )

        local_results: list[SearchResult] = []
        for query in probe_plan.local_queries[:4]:
            local_results.extend(
                await _safe_search(
                    "local_rag",
                    query=query.query,
                    subject=state["subject"],
                    local_sections=local_sections,
                )
            )
        if not local_results and local_sections:
            fallback_queries = _fallback_local_queries(state)
            logger.info(
                "planner_probe_retrying_local_queries",
                planner_session_id=state.get("planner_session_id") or "",
                subject=state["subject"],
                fallback_queries=fallback_queries,
            )
            for query in fallback_queries:
                local_results.extend(
                    await _safe_search(
                        "local_rag",
                        query=query,
                        subject=state["subject"],
                        local_sections=local_sections,
                    )
                )

        web_results: list[SearchResult] = []
        if get_settings().planner_allow_external_search and probe_plan.source_policy != "local_only":
            external_names = [
                name
                for name in get_settings().parse_retrievers(
                    profile=state.get("retrieval_profile"),
                    include_local_rag=False,
                    include_fallback=True,
                )
                if name not in {"local_rag", "rag"}
            ]
            for query in probe_plan.web_queries[:2]:
                for retriever_name in external_names[:2]:
                    hits = await _safe_search(
                        retriever_name,
                        query=query.query,
                        subject=state["subject"],
                        local_sections=local_sections,
                    )
                    if hits:
                        web_results.extend(hits)
                        break

        curator_meta: dict[str, object] = {}
        try:
            curator = SourceCurator(TracedExecutionContext(subject=state["subject"], workflow_context=context))
            curated_web, curator_meta = await curator.curate_sources(
                query=" ".join(query.query for query in probe_plan.web_queries[:2]),
                sources=web_results,
                max_results=2,
            )
        except Exception:
            curated_web = web_results[:2]
        selected_sources: list[PlannerSelectedSource] = [
            *rule_based_source_triage(local_results, limit=4, source_type="local"),
            *rule_based_source_triage(curated_web, limit=2, source_type="web"),
        ]
        await emit_planner_event(
            state,
            event="planner.sources.triaged",
            detail=f"已筛选 {len(selected_sources)} 个候选来源。",
            payload={
                "selected_source_count": len(selected_sources),
                "selected_source_titles": [
                    source.title
                    for source in selected_sources[:4]
                    if str(source.title or "").strip()
                ],
            },
        )

        opened_sources: list[PlannerOpenedSource] = []
        for source in selected_sources:
            if source.source_type == "local":
                opened_sources.append(
                    PlannerOpenedSource(
                        title=source.title,
                        url=source.url,
                        source_type="local",
                        content_preview=_source_preview(source.snippet),
                    )
                )
        web_urls = [source.url for source in selected_sources if source.source_type == "web" and source.url][:2]
        if web_urls:
            try:
                pages = await read_urls(web_urls, max_workers=2, timeout_s=float(get_settings().search_read_timeout_s))
                for page in pages:
                    opened_sources.append(
                        PlannerOpenedSource(
                            title=page.title or page.url,
                            url=page.url,
                            source_type="web",
                            content_preview=_source_preview(page.content if page.success else page.error),
                        )
                    )
            except Exception:
                pass

        topic_titles = [
            source.title
            for source in opened_sources[:5]
            if source.title
        ]
        core_concepts = _collect_core_concepts(
            state=state,
            local_results=local_results,
            opened_sources=opened_sources,
        )
        concept_briefing = (
            "已读取的规划证据："
            + ("；".join(topic_titles) if topic_titles else "暂无可用证据，使用资料画像和用户目标规划。")
            + (f"。重点概念包括：{'、'.join(core_concepts[:6])}" if core_concepts else "")
        )
        evidence = EvidenceBrief(
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
                    evidence_summary=(
                        f"重点覆盖 {title} 及相关概念，避免只罗列术语。"
                    ),
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
        await emit_planner_event(
            state,
            event="planner.evidence.ready",
            detail=f"证据探测完成，本地命中 {len(local_results)}，外部命中 {len(web_results)}。",
            payload={
                "local_hit_count": len(local_results),
                "web_hit_count": len(web_results),
                "opened_source_count": len(opened_sources),
                "selected_source_titles": topic_titles[:4],
                "core_concepts": core_concepts[:6],
                "concept_briefing": concept_briefing,
            },
        )
        logger.info(
            "planner_probe_completed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state["subject"],
            local_sections_count=len(local_sections),
            local_hit_count=len(local_results),
            web_hit_count=len(web_results),
            opened_source_count=len(opened_sources),
        )
        return {
            "selected_sources": [source.model_dump(mode="json") for source in selected_sources],
            "opened_sources": [source.model_dump(mode="json") for source in opened_sources],
            "evidence_brief": evidence.model_dump(mode="json"),
            "concept_briefing": evidence.concept_briefing,
            "concept_local_hit_count": len(local_results),
            "concept_web_hit_count": len(web_results),
        }

    return probe_evidence_node


__all__ = ["build_probe_evidence_node"]
