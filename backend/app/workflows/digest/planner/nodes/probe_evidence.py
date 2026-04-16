"""Probe local/web evidence for Planner V3."""

from __future__ import annotations

import structlog

from app.shared.infra.settings import get_settings
from app.shared.infra.execution import TracedExecutionContext
from app.shared.infra.search import SourceCurator
from app.shared.infra.search.types import SearchResult
from app.shared.infra.tools.builtin.web_reading import read_urls
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.digest.planner.lib.evidence_probe import (
    build_evidence_brief,
    fallback_local_queries,
    safe_search,
    source_preview,
)
from app.workflows.digest.planner.lib.planner_events import emit_planner_event
from app.workflows.digest.planner.lib.research_probe import (
    LearningIntentProfile,
    PlanSketch,
    PlannerOpenedSource,
    PlannerSelectedSource,
    ResearchProbePlan,
)
from app.workflows.digest.planner.lib.source_triage import rule_based_source_triage
from app.workflows.digest.planner.state import BuildPlannerState

logger = structlog.get_logger(__name__)


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
                await safe_search(
                    "local_rag",
                    query=query.query,
                    subject=state["subject"],
                    local_sections=local_sections,
                )
            )
        if not local_results and local_sections:
            fallback_queries = fallback_local_queries(material_context, plan_sketch=plan_sketch)
            logger.info(
                "planner_probe_retrying_local_queries",
                planner_session_id=state.get("planner_session_id") or "",
                subject=state["subject"],
                fallback_queries=fallback_queries,
            )
            for query in fallback_queries:
                local_results.extend(
                    await safe_search(
                        "local_rag",
                        query=query,
                        subject=state["subject"],
                        local_sections=local_sections,
                    )
                )

        web_results: list[SearchResult] = []
        if get_settings().planner.allow_external_search and probe_plan.source_policy != "local_only":
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
                    hits = await safe_search(
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
                        content_preview=source_preview(source.snippet),
                    )
                )
        web_urls = [source.url for source in selected_sources if source.source_type == "web" and source.url][:2]
        if web_urls:
            try:
                pages = await read_urls(web_urls, max_workers=2, timeout_s=float(get_settings().search.read_timeout_s))
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
            detail=f"证据探测完成，本地命中 {len(local_results)}，外部命中 {len(web_results)}。",
            payload={
                "local_hit_count": len(local_results),
                "web_hit_count": len(web_results),
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
            "evidence_brief": evidence.model_dump(mode="json"),
        }

    return probe_evidence_node


__all__ = ["build_probe_evidence_node"]
