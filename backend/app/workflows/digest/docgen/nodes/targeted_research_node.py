"""Targeted research node for the DocGen lane."""

from __future__ import annotations

from copy import deepcopy
from time import perf_counter

from app.shared.infra.config import get_settings
from app.shared.infra.skills import ResearchConductor, SkillContext
from app.shared.infra.tools.builtin.markdown_processing import build_draft_excerpt
from app.workflows.common.context import WorkflowContext
from app.workflows.digest.docgen.nodes.common import publish_docgen_progress, resolve_docgen_dependency
from app.workflows.digest.docgen.state import DocGenState


def build_targeted_research_node(*, context: WorkflowContext):
    async def targeted_research_node(state: DocGenState) -> dict:
        started_at = perf_counter()
        assignment = deepcopy(state["chapter_assignment"])
        skill_context = SkillContext(
            subject=state["subject"],
            build_session_id=state.get("build_session_id", ""),
            workflow_context=context,
            planner_session_id=state.get("planner_session_id", ""),
            confirmed_plan_id=state.get("confirmed_plan_id", ""),
            digest_mode=state.get("digest_mode", ""),
            chapter_index=int(assignment.get("chapter_index", 0) or 0),
        )
        researcher_cls = resolve_docgen_dependency("ResearchConductor", ResearchConductor)
        researcher = researcher_cls(skill_context)
        shared_inputs = state.get("shared_inputs")
        section_packets = list(getattr(shared_inputs, "section_packets", []) or [])
        queries = [
            str(item).strip()
            for item in assignment.get("search_queries", [])
            if str(item).strip()
        ]
        if not queries:
            queries = [str(assignment.get("title") or "").strip()]
        result = await researcher.run(
            queries=queries[: max(1, int(get_settings().docgen_max_research_queries))],
            local_rag_subject=state["subject"],
            local_sections=section_packets,
            chapter_title=str(assignment.get("title") or ""),
            objective=str(assignment.get("objective") or ""),
            required_elements=list(assignment.get("required_elements") or []),
            digest_mode=state.get("digest_mode") or "",
        )
        dense_context = result.content.strip()
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        chapter_material = {
            **assignment,
            "dense_context": dense_context,
            "sources": list(result.sources),
            "source_details": list(result.metadata.get("source_details", [])),
            "research_summary": build_draft_excerpt(dense_context, max_chars=320) if dense_context else "",
            "research_ms": elapsed_ms,
            "local_hits": int(result.metadata.get("local_hits", 0)),
            "web_hits": int(result.metadata.get("web_hits", 0)),
            "fallback_used": bool(result.metadata.get("fallback_used", False)),
            "compression_mode": str(result.metadata.get("compression_mode", "")),
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
        }
        await publish_docgen_progress(
            context,
            state=state,
            stage="research_chapter_completed",
            payload={
                "chapter_index": chapter_material["chapter_index"],
                "title": chapter_material["title"],
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
