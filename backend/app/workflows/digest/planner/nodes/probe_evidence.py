"""Probe evidence for Planner V3."""

from __future__ import annotations

import asyncio

import structlog

from app.shared.infra.llm_support import acompletion_with_fallback
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.search import SourceCurator
from app.shared.infra.search.factory import get_configured_retriever_names
from app.shared.infra.search.types import SearchResult
from app.shared.infra.settings import get_settings
from app.shared.infra.tools.builtin.web_reading import read_urls
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.evidence_probe import (
    build_evidence_brief,
    fallback_probe_queries,
    rule_based_source_triage,
    safe_search,
    source_preview,
)
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.lib.models import (
    PlanSketch,
    PlannerOpenedSource,
    PlannerProbeQuerySet,
    PlannerSelectedSource,
)
from app.workflows.digest.planner.prompts import build_evidence_query_messages
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


def _normalize_probe_queries(value: list[str], *, limit: int) -> list[str]:
    queries: list[str] = []
    seen: set[str] = set()
    for item in value:
        query = str(item or "").strip()
        if not query:
            continue
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        queries.append(query)
        if len(queries) >= limit:
            break
    return queries


async def _generate_probe_queries(state: BuildPlannerState, *, plan_sketch: PlanSketch) -> list[str]:
    settings = get_settings()
    query_count = max(1, int(settings.planner.evidence_query_count))
    material_context = state["material_context"]
    fallback_queries = fallback_probe_queries(material_context, plan_sketch=plan_sketch)
    try:
        generated = await acompletion_with_fallback(
            build_evidence_query_messages(
                subject=state["subject"],
                user_goal=state.get("user_goal") or "",
                material_context=material_context,
                plan_sketch=plan_sketch,
                query_count=query_count,
            ),
            task_type=TaskType.CLASSIFY,
            model="light",
            response_model=PlannerProbeQuerySet,
            temperature=0.1,
            max_tokens=420,
            extra_metadata={
                "planner_session_id": state.get("planner_session_id") or "",
                "substep": "generate_probe_queries",
            },
        )
        queries = _normalize_probe_queries(generated.queries, limit=query_count)
        if queries:
            return queries
    except Exception:
        logger.exception(
            "planner_probe_query_generation_failed",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state["subject"],
        )
    return _normalize_probe_queries(fallback_queries, limit=query_count)


def build_probe_evidence_node(*, context: WorkflowContext):
    async def probe_evidence_node(state: BuildPlannerState) -> dict:
        material_context = state["material_context"]
        plan_sketch = PlanSketch.model_validate(state.get("plan_sketch") or {})
        settings = get_settings()
        queries = await _generate_probe_queries(state, plan_sketch=plan_sketch)
        if not queries:
            fallback_query = str(state.get("user_goal") or state["subject"]).strip()
            queries = [fallback_query] if fallback_query else []
        local_sections = list(material_context.material_sections)
        retriever_names = get_configured_retriever_names(
            profile=state.get("retrieval_profile"),
            include_local_rag=True,
            include_fallback=True,
        )
        logger.info(
            "planner_probe_started",
            planner_session_id=state.get("planner_session_id") or "",
            subject=state["subject"],
            local_sections_count=len(local_sections),
            query_count=len(queries),
            retriever_names=retriever_names,
        )
        await emit_planner_event(
            state,
            event="planner.probe.started",
            detail="正在调用全部可用检索器，校准概念边界和大纲结构...",
            payload={
                "query_count": len(queries),
                "retriever_count": len(retriever_names),
                "retriever_names": retriever_names,
                "local_sections_count": len(local_sections),
                "queries": queries,
                "local_queries": queries,
                "web_queries": queries,
            },
        )

        local_results: list[SearchResult] = []
        web_results: list[SearchResult] = []
        if retriever_names:
            async def _run_search(retriever_name: str, query: str) -> tuple[str, list[SearchResult]]:
                return retriever_name, await safe_search(
                    retriever_name,
                    query=query,
                    subject=state["subject"],
                    local_sections=local_sections,
                )

            search_jobs = [
                _run_search(retriever_name, query)
                for query in queries
                for retriever_name in retriever_names
            ]
            search_results = await asyncio.gather(*search_jobs, return_exceptions=True)
            for result in search_results:
                if not isinstance(result, tuple):
                    continue
                retriever_name, hits = result
                if retriever_name in {"local_rag", "rag"}:
                    local_results.extend(hits)
                else:
                    web_results.extend(hits)

        curator_meta: dict[str, object] = {}
        curated_web: list[SearchResult] = []
        if web_results:
            try:
                curator = SourceCurator(TracedExecutionContext(subject=state["subject"], workflow_context=context))
                curated_web, curator_meta = await curator.curate_sources(
                    query=" ".join(queries[:2]),
                    sources=web_results,
                    max_results=4,
                )
            except Exception:
                curated_web = web_results[:4]
        selected_sources: list[PlannerSelectedSource] = rule_based_source_triage(
            local_results,
            limit=4,
            source_type="local",
        ) + rule_based_source_triage(
            curated_web,
            limit=4,
            source_type="web",
        )
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
                        content_preview=source_preview(source.snippet),
                    )
                )
        open_source_limit = max(1, int(settings.planner.evidence_open_source_limit))
        web_urls = [
            source.url
            for source in selected_sources
            if source.source_type == "web" and source.url
        ][:open_source_limit]
        if web_urls:
            try:
                pages = await read_urls(
                    web_urls,
                    max_workers=min(open_source_limit, max(1, int(settings.search.max_parallel_retrievers))),
                    timeout_s=float(settings.search.read_timeout_s),
                )
                for page in pages:
                    opened_sources.append(
                        PlannerOpenedSource(
                            title=page.title or page.url,
                            url=page.url,
                            source_type="web",
                            content_preview=source_preview(page.content if page.success else page.error),
                        )
                    )
            except Exception:
                pass

        evidence = build_evidence_brief(
            material_context=material_context,
            plan_sketch=plan_sketch,
            selected_sources=selected_sources,
            opened_sources=opened_sources,
            local_results=local_results,
            web_results=web_results,
            curator_meta=curator_meta,
        )
        await emit_planner_event(
            state,
            event="planner.evidence.ready",
            detail=f"检索证据整理完成，本地命中 {len(local_results)} 条，外部命中 {len(web_results)} 条。",
            payload={
                "local_hit_count": len(local_results),
                "web_hit_count": len(web_results),
                "retriever_names": retriever_names,
                "opened_source_count": len(opened_sources),
                "selected_source_titles": [source.title for source in opened_sources[:4] if source.title],
                "core_concepts": evidence.core_concepts[:6],
                "concept_briefing": evidence.concept_briefing,
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
            "concept_topic_hints": list(evidence.core_concepts),
            "concept_local_hit_count": len(local_results),
            "concept_web_hit_count": len(web_results),
        }

    return probe_evidence_node


__all__ = ["build_probe_evidence_node"]
