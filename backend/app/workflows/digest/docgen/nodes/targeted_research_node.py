"""Targeted research node for the DocGen lane."""

from __future__ import annotations

from copy import deepcopy
from time import perf_counter
from urllib.parse import urlparse

from app.shared.infra.config import get_settings
from app.shared.infra.traced_execution import TracedExecutionContext
from app.shared.infra.tools.builtin.markdown_processing import build_draft_excerpt
from app.utils.docgen_store import append_knowledge_build_recent_event, upsert_knowledge_build_chapter_progress
from app.utils.time import utcnow
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.runtime import DocGenResearchRuntime as ResearchConductor
from app.workflows.digest.docgen.nodes.common import (
    get_effective_chapter_title,
    publish_docgen_progress,
    resolve_docgen_course_type,
    resolve_docgen_dependency,
    resolve_docgen_retrieval_profile,
)
from app.workflows.digest.docgen.state import DocGenState


def _extract_external_source_preview(source_details: list[dict[str, object]]) -> tuple[list[str], list[str]]:
    source_titles: list[str] = []
    source_urls: list[str] = []
    seen: set[str] = set()
    for item in source_details:
        url = str(item.get("url") or "").strip()
        if not url or url.startswith("local://") or url in seen:
            continue
        seen.add(url)
        title = str(item.get("title") or "").strip() or url
        source_titles.append(title)
        source_urls.append(url)
        if len(source_urls) >= 4:
            break
    return source_titles, source_urls


def _extract_top_domains(result_metadata: dict[str, object], source_urls: list[str]) -> list[str]:
    top_domains = result_metadata.get("top_domains")
    if isinstance(top_domains, dict):
        domains = [str(domain).strip() for domain in top_domains.keys() if str(domain).strip()]
        if domains:
            return domains[:4]

    normalized: list[str] = []
    seen: set[str] = set()
    for url in source_urls:
        domain = urlparse(url).netloc.strip().lower()
        if not domain or domain in seen:
            continue
        seen.add(domain)
        normalized.append(domain)
        if len(normalized) >= 4:
            break
    return normalized


def build_targeted_research_node(*, context: WorkflowContext):
    async def targeted_research_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        assignment = deepcopy(state["chapter_assignment"])
        chapter_index = int(assignment.get("chapter_index", 0) or 0)
        chapter_title = get_effective_chapter_title(assignment, fallback_index=chapter_index)
        upsert_knowledge_build_chapter_progress(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_progress={
                "chapter_index": chapter_index,
                "title": chapter_title,
                "status": "researching",
            },
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "researching",
                "chapter_index": chapter_index,
                "title": chapter_title,
                "summary": f"{chapter_title} 开始研究，正在检索资料与整理上下文。",
                "created_at": utcnow(),
            },
        )

        traced_context = TracedExecutionContext(
            subject=state["subject"],
            build_session_id=state.get("build_session_id", ""),
            workflow_context=context,
            planner_session_id=state.get("planner_session_id", ""),
            confirmed_plan_id=state.get("confirmed_plan_id", ""),
            digest_mode=state.get("digest_mode", ""),
            course_type=resolve_docgen_course_type(state.get("course_type") or state.get("digest_mode")),
            retrieval_profile=str(state.get("retrieval_profile") or resolve_docgen_retrieval_profile(state.get("digest_mode"))),
            teaching_action=str(state.get("teaching_action") or "chapter_research"),
            chapter_index=chapter_index,
        )
        researcher_cls = resolve_docgen_dependency("ResearchConductor", ResearchConductor, owner_module=__name__)
        researcher = researcher_cls(traced_context)
        shared_inputs = state.get("shared_inputs")
        section_packets = list(getattr(shared_inputs, "section_packets", []) or [])
        queries = [
            str(item).strip()
            for item in assignment.get("search_queries", [])
            if str(item).strip()
        ]
        if not queries:
            queries = [chapter_title]
        result = await researcher.run(
            queries=queries[: max(1, int(get_settings().docgen_max_research_queries))],
            local_rag_subject=state["subject"],
            local_sections=section_packets,
            chapter_title=chapter_title,
            objective=str(assignment.get("objective") or ""),
            required_elements=list(assignment.get("required_elements") or []),
            digest_mode=state.get("digest_mode") or "",
            retrieval_profile=traced_context.retrieval_profile,
            selected_skillpacks=list(state.get("selected_skillpacks") or []),
            user_goal=str((state.get("document_context") or {}).get("user_goal") or ""),
        )
        dense_context = result.content.strip()
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        source_details = list(result.metadata.get("source_details", []))
        source_titles, source_urls = _extract_external_source_preview(source_details)
        domains = _extract_top_domains(dict(result.metadata), source_urls)
        chapter_material = {
            **assignment,
            "course_type": traced_context.course_type,
            "retrieval_profile": traced_context.retrieval_profile,
            "teaching_action": traced_context.teaching_action,
            "dense_context": dense_context,
            "sources": list(result.sources),
            "source_details": source_details,
            "source_titles": source_titles,
            "source_urls": source_urls,
            "research_summary": build_draft_excerpt(dense_context, max_chars=320) if dense_context else "",
            "research_ms": elapsed_ms,
            "local_hits": int(result.metadata.get("local_hits", 0)),
            "web_hits": int(result.metadata.get("web_hits", 0)),
            "fallback_used": bool(result.metadata.get("fallback_used", False)),
            "compression_mode": str(result.metadata.get("compression_mode", "")),
            "requested_retrieval_profile": str(result.metadata.get("requested_retrieval_profile") or traced_context.retrieval_profile),
            "applied_retrieval_profile": str(result.metadata.get("applied_retrieval_profile") or traced_context.retrieval_profile),
            "requested_profile": str(result.metadata.get("requested_profile") or traced_context.retrieval_profile or "default"),
            "applied_profile": str(result.metadata.get("applied_profile") or traced_context.retrieval_profile or "default"),
            "configured_retrievers": list(result.metadata.get("configured_retrievers", [])),
            "active_retrievers": list(result.metadata.get("active_retrievers", [])),
            "executed_queries": list(result.metadata.get("executed_queries", [])),
            "base_queries": list(result.metadata.get("base_queries", [])),
            "planned_queries": list(result.metadata.get("planned_queries", [])),
            "fallback_queries": list(result.metadata.get("fallback_queries", [])),
            "query_count": int(result.metadata.get("query_count", 0) or 0),
            "scraped_url_count": int(result.metadata.get("scraped_url_count", 0) or 0),
            "document_count": int(result.metadata.get("document_count", 0) or 0),
            "purify_used": bool(result.metadata.get("purify_used", False)),
            "curated_source_count": int(result.metadata.get("curated_source_count", 0)),
            "trusted_source_count": int(result.metadata.get("trusted_source_count", 0) or 0),
            "local_source_count": int(result.metadata.get("local_source_count", 0) or 0),
            "web_source_count": int(result.metadata.get("web_source_count", 0) or 0),
            "unique_domain_count": int(result.metadata.get("unique_domain_count", 0) or 0),
            "top_domains": dict(result.metadata.get("top_domains", {}) or {}),
            "retriever_stats": dict(result.metadata.get("retriever_stats", {}) or {}),
            "research_rounds": list(result.metadata.get("research_rounds", []) or []),
            "research_round_count": int(result.metadata.get("research_round_count", 0) or 0),
            "gaps_remaining": list(result.metadata.get("gaps_remaining", []) or []),
            "coverage_score": float(result.metadata.get("coverage_score", 0.0) or 0.0),
            "source_class_breakdown": dict(result.metadata.get("source_class_breakdown", {}) or {}),
            "stop_reason": str(result.metadata.get("stop_reason", "") or ""),
            "selected_skillpacks": list(result.metadata.get("selected_skillpacks", []) or []),
            "recommended_tool_tags": list(result.metadata.get("recommended_tool_tags", []) or []),
        }
        upsert_knowledge_build_chapter_progress(
            state["subject"],
            requested_at=state["requested_at"],
            chapter_progress={
                "chapter_index": chapter_index,
                "title": chapter_title,
                "status": "researched",
                "source_count": len(chapter_material["sources"]),
                "local_hits": chapter_material["local_hits"],
                "web_hits": chapter_material["web_hits"],
                "query_count": chapter_material["query_count"],
                "fallback_used": chapter_material["fallback_used"],
            },
        )
        append_knowledge_build_recent_event(
            state["subject"],
            requested_at=state["requested_at"],
            event={
                "stage": "research_completed",
                "chapter_index": chapter_index,
                "title": chapter_title,
                "summary": f"{chapter_title} 研究完成，本地命中 {chapter_material['local_hits']}，外部命中 {chapter_material['web_hits']}，整理来源 {len(chapter_material['sources'])}。",  # noqa: E501
                "created_at": utcnow(),
                "domains": domains,
                "source_titles": source_titles,
                "source_urls": source_urls,
            },
        )
        await publish_docgen_progress(
            context,
            state=state,
            stage="research_chapter_completed",
            payload={
                "chapter_index": chapter_material["chapter_index"],
                "title": get_effective_chapter_title(chapter_material, fallback_index=chapter_index),
                "source_count": len(chapter_material["sources"]),
                "local_hits": chapter_material["local_hits"],
                "web_hits": chapter_material["web_hits"],
                "fallback_used": chapter_material["fallback_used"],
                "query_count": chapter_material["query_count"],
                "curated_source_count": chapter_material["curated_source_count"],
            },
        )
        return {
            "chapter_materials": [chapter_material],
            "research_sources": list(result.sources),
            "research_ms": elapsed_ms,
            "llm_calls_total": 1 if bool(result.metadata.get("purify_used", False)) else 0,
        }

    return targeted_research_node


__all__ = ["build_targeted_research_node"]

