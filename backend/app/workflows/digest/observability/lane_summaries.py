"""Per-lane digest summary builders (DocGen, KG, Curriculum)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.shared.infra.tools.builtin.markdown_processing import count_words

from .models import DigestTokenSummary, SlowItemTiming


def build_slow_items(
    items: Sequence[Mapping[str, Any] | SlowItemTiming],
    *,
    top_k: int | None = None,
) -> list[SlowItemTiming]:
    """Normalize and trim slow item records."""

    limit = _top_k(top_k)
    normalized: list[SlowItemTiming] = []
    for item in items:
        if isinstance(item, SlowItemTiming):
            normalized.append(item)
            continue
        normalized.append(
            SlowItemTiming(
                item_id=str(item.get("item_id") or item.get("chunk_id") or item.get("chapter_index") or item.get("title") or "item"),
                title=str(item.get("title") or item.get("name") or item.get("chunk_title") or ""),
                elapsed_ms=int(item.get("elapsed_ms", 0)),
                metadata={
                    key: value
                    for key, value in item.items()
                    if key not in {"item_id", "title", "name", "chunk_id", "chapter_index", "chunk_title", "elapsed_ms"}
                },
            )
        )
    normalized.sort(key=lambda entry: (-entry.elapsed_ms, entry.item_id))
    return normalized[:limit]


def add_slow_item(
    items: list[dict[str, Any]],
    *,
    item_id: str,
    title: str,
    elapsed_ms: int,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Append a slow item and keep only the slowest top-k entries."""

    items.append(
        {
            "item_id": item_id,
            "title": title,
            "elapsed_ms": int(elapsed_ms),
            **(metadata or {}),
        }
    )
    items.sort(key=lambda item: (-int(item.get("elapsed_ms", 0)), str(item.get("item_id", ""))))
    del items[_top_k() :]
    return items


def step_slow_items(step_map: Mapping[str, int], *, top_k: int | None = None) -> list[SlowItemTiming]:
    """Turn a simple step->elapsed map into ranked slow items."""

    return build_slow_items(
        [
            {"item_id": step_name, "title": step_name, "elapsed_ms": elapsed_ms}
            for step_name, elapsed_ms in step_map.items()
            if int(elapsed_ms) > 0
        ],
        top_k=top_k,
    )


def build_docgen_lane_summary(
    state: Mapping[str, Any],
    *,
    token_summary: DigestTokenSummary,
    status: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Create a DocGen lane summary payload."""

    resolved_status = _resolve_status(state, status=status, error_message=error_message)
    resolved_error = _resolve_error_message(state, error_message=error_message)
    chapter_materials = list(state.get("chapter_materials", []))
    chapter_drafts = list(state.get("chapter_drafts", []))
    chapter_metadatas = list(state.get("chapter_metadatas", []))
    document_context = dict(state.get("document_context", {}) or {})
    chapter_count = max(len(chapter_metadatas), len(chapter_drafts), len(chapter_materials))
    research_items = build_slow_items(
        state.get("slowest_research_chapters")
        or [
            {
                "item_id": f"chapter_{material.get('chapter_index', index)}",
                "title": str(material.get("title", "")),
                "elapsed_ms": int(material.get("research_ms", 0)),
                "source_count": len(material.get("sources", [])),
                "local_hits": int(material.get("local_hits", 0)),
                "web_hits": int(material.get("web_hits", 0)),
            }
            for index, material in enumerate(chapter_materials, start=1)
        ]
    )
    draft_items = build_slow_items(
        state.get("slowest_draft_chapters")
        or [
            {
                "item_id": f"chapter_{draft.get('chapter_index', index)}",
                "title": str(draft.get("title", "")),
                "elapsed_ms": int(draft.get("draft_ms", 0)),
                "word_count": int(draft.get("word_count", 0)),
                "placeholder_count": int(draft.get("placeholder_count", 0)),
            }
            for index, draft in enumerate(chapter_drafts, start=1)
        ]
    )
    final_markdown = str(state.get("enriched_markdown") or state.get("merged_markdown") or "")
    source_urls = [
        str(url)
        for url in [*state.get("research_sources", []), *[source for chapter in chapter_metadatas for source in chapter.get("sources", [])]]
        if str(url).strip()
    ]
    total_sources = len(dict.fromkeys(source_urls))
    placeholder_count = sum(int(chapter.get("placeholder_count", 0)) for chapter in chapter_drafts)
    local_hit_count = sum(int(chapter.get("local_hits", 0) or 0) for chapter in chapter_materials)
    web_hit_count = sum(int(chapter.get("web_hits", 0) or 0) for chapter in chapter_materials)
    fallback_chapter_count = sum(1 for chapter in chapter_materials if bool(chapter.get("fallback_used", False)))
    curated_source_count = sum(int(chapter.get("curated_source_count", 0) or 0) for chapter in chapter_materials)
    trusted_source_count = sum(int(chapter.get("trusted_source_count", 0) or 0) for chapter in chapter_materials)
    retrieval_profiles = sorted(
        {
            str(chapter.get("retrieval_profile") or "").strip()
            for chapter in chapter_materials
            if str(chapter.get("retrieval_profile") or "").strip()
        }
    )
    if not retrieval_profiles and str(state.get("retrieval_profile") or "").strip():
        retrieval_profiles = [str(state.get("retrieval_profile") or "").strip()]
    teaching_actions = sorted(
        {
            str(item.get("teaching_action") or "").strip()
            for item in [*chapter_materials, *chapter_drafts]
            if str(item.get("teaching_action") or "").strip()
        }
    )
    if not teaching_actions and str(state.get("teaching_action") or "").strip():
        teaching_actions = [str(state.get("teaching_action") or "").strip()]
    planned_query_count = sum(len(chapter.get("planned_queries", []) or []) for chapter in chapter_materials)
    executed_query_count = sum(len(chapter.get("executed_queries", []) or []) for chapter in chapter_materials)
    read_url_count = sum(int(chapter.get("read_url_count", 0) or 0) for chapter in chapter_materials)
    research_document_count = sum(int(chapter.get("document_count", 0) or 0) for chapter in chapter_materials)
    purify_chapter_count = sum(1 for chapter in chapter_materials if bool(chapter.get("purify_used", False)))
    retriever_names = sorted(
        {
            str(retriever_name)
            for chapter in chapter_materials
            for retriever_name in dict(chapter.get("retriever_stats", {}) or {}).keys()
            if str(retriever_name).strip()
        }
    )
    active_retriever_names = sorted(
        {
            str(retriever_name).strip()
            for chapter in chapter_materials
            for retriever_name in list(chapter.get("active_retrievers", []) or [])
            if str(retriever_name).strip()
        }
    )
    configured_retriever_names = sorted(
        {
            str(retriever_name).strip()
            for chapter in chapter_materials
            for retriever_name in list(chapter.get("configured_retrievers", []) or [])
            if str(retriever_name).strip()
        }
    )
    applied_retrieval_profiles = sorted(
        {
            str(chapter.get("applied_retrieval_profile") or "").strip()
            for chapter in chapter_materials
            if str(chapter.get("applied_retrieval_profile") or "").strip()
        }
    )
    requested_profiles = sorted(
        {
            str(chapter.get("requested_profile") or chapter.get("requested_retrieval_profile") or "").strip()
            for chapter in chapter_materials
            if str(chapter.get("requested_profile") or chapter.get("requested_retrieval_profile") or "").strip()
        }
    )
    applied_profiles = sorted(
        {
            str(chapter.get("applied_profile") or chapter.get("applied_retrieval_profile") or "").strip()
            for chapter in chapter_materials
            if str(chapter.get("applied_profile") or chapter.get("applied_retrieval_profile") or "").strip()
        }
    )
    research_rounds = [
        {
            "chapter_index": int(chapter.get("chapter_index", 0) or 0),
            "title": str(chapter.get("resolved_title") or chapter.get("title") or ""),
            "round_count": int(chapter.get("research_round_count", 0) or len(chapter.get("research_rounds", []) or [])),
        }
        for chapter in chapter_materials
    ]
    gaps_remaining = sorted(
        {
            str(gap).strip()
            for chapter in chapter_materials
            for gap in list(chapter.get("gaps_remaining", []) or [])
            if str(gap).strip()
        }
    )[:12]
    source_class_breakdown = _sum_count_maps(
        [dict(chapter.get("source_class_breakdown", {}) or {}) for chapter in chapter_materials]
    )
    interactive_block_count = int(state.get("interactive_block_count", 0) or 0) or sum(
        int(chapter.get("interactive_block_count", 0) or 0)
        for chapter in [*chapter_drafts, *chapter_metadatas]
    )
    mermaid_block_count = int(state.get("mermaid_block_count", 0) or 0)
    if mermaid_block_count <= 0:
        mermaid_block_count = sum(
            int(str(chapter.get("markdown") or "").count("```mermaid"))
            for chapter in chapter_metadatas
        )
    image_block_count = int(state.get("image_block_count", 0) or 0)
    if image_block_count <= 0:
        image_block_count = sum(
            int(str(chapter.get("markdown") or "").count("建议配图："))
            + int(str(chapter.get("markdown") or "").count("配图建议占位："))
            for chapter in chapter_metadatas
        )
    asset_summary = {
        "mermaid": mermaid_block_count,
        "image": image_block_count,
        "interactive_html": interactive_block_count,
        "animation": int(((state.get("asset_summary") or {}) if isinstance(state.get("asset_summary"), Mapping) else {}).get("animation", 0) or 0),
    }
    asset_count = int(state.get("asset_count", 0) or 0) or sum(asset_summary.values())
    practice_count = int(state.get("practice_count", 0) or 0) or sum(
        int(chapter.get("practice_count", 0) or 0)
        for chapter in chapter_metadatas
    ) or len(state.get("exam_questions", []))
    coverage_scores = [
        float(chapter.get("coverage_score", 0.0) or 0.0)
        for chapter in [*chapter_drafts, *chapter_materials]
        if float(chapter.get("coverage_score", 0.0) or 0.0) > 0
    ]
    quality_scores = [
        float(chapter.get("quality_score", 0.0) or 0.0)
        for chapter in chapter_drafts
        if float(chapter.get("quality_score", 0.0) or 0.0) > 0
    ]
    repaired_chapter_count = sum(1 for chapter in chapter_drafts if bool(chapter.get("repair_applied", False)))
    selected_skillpacks = sorted(
        {
            str(item).strip()
            for item in (
                list(state.get("selected_skillpacks", []) or [])
                + list(document_context.get("selected_skillpacks", []) or [])
                + [
                    skill
                    for chapter in [*chapter_materials, *chapter_drafts]
                    for skill in list(chapter.get("selected_skillpacks", []) or [])
                ]
            )
            if str(item).strip()
        }
    )
    return {
        "status": resolved_status,
        "error_message": resolved_error,
        "planner_session_id": str(state.get("planner_session_id", "") or ""),
        "confirmed_plan_id": str(state.get("confirmed_plan_id", "") or ""),
        "digest_mode": str(state.get("digest_mode", "") or ""),
        "course_type": str(
            state.get("course_type", "")
            or document_context.get("course_type", "")
            or state.get("digest_mode", "")
            or ""
        ),
        "source_strategy": str(document_context.get("source_strategy", "") or ""),
        "selected_skillpacks": selected_skillpacks,
        "retrieval_profiles": retrieval_profiles,
        "teaching_actions": teaching_actions,
        "chapter_count": chapter_count,
        "workflow_elapsed_ms": int(state.get("workflow_elapsed_ms", 0)),
        "load_ms": int(state.get("load_ms", 0)),
        "planner_ms": int(state.get("planner_ms", 0)),
        "research_ms": int(state.get("research_ms", 0)),
        "draft_ms": int(state.get("draft_ms", 0)),
        "enrich_ms": int(state.get("enrich_ms", 0)),
        "examine_ms": int(state.get("examine_ms", 0)),
        "finalize_ms": int(state.get("finalize_ms", 0)),
        "research_avg_ms": round(int(state.get("research_ms", 0)) / chapter_count, 2) if chapter_count else 0.0,
        "draft_avg_ms": round(int(state.get("draft_ms", 0)) / chapter_count, 2) if chapter_count else 0.0,
        "llm_calls_total": int(state.get("llm_calls_total", 0)),
        "llm_calls_skipped": int(state.get("llm_calls_skipped", 0)),
        "draft_available": bool(final_markdown.strip()),
        "staged_chapter_count": len(chapter_metadatas),
        "published_doc_count": len(state.get("doc_ids", [])),
        "research_source_count": total_sources,
        "exam_question_count": len(state.get("exam_questions", [])),
        "local_hit_count": local_hit_count,
        "web_hit_count": web_hit_count,
        "fallback_chapter_count": fallback_chapter_count,
        "curated_source_count": curated_source_count,
        "trusted_source_count": trusted_source_count,
        "retriever_names": retriever_names,
        "retriever_count": len(retriever_names),
        "active_retriever_names": active_retriever_names,
        "active_retriever_count": len(active_retriever_names),
        "configured_retriever_names": configured_retriever_names,
        "configured_retriever_count": len(configured_retriever_names),
        "requested_profiles": requested_profiles,
        "applied_profiles": applied_profiles,
        "requested_profile": requested_profiles[0] if len(requested_profiles) == 1 else "",
        "applied_profile": applied_profiles[0] if len(applied_profiles) == 1 else "",
        "applied_retrieval_profiles": applied_retrieval_profiles,
        "planned_query_count": planned_query_count,
        "executed_query_count": executed_query_count,
        "read_url_count": read_url_count,
        "research_document_count": research_document_count,
        "purify_chapter_count": purify_chapter_count,
        "research_rounds": research_rounds,
        "research_round_count_total": sum(int(item.get("round_count", 0) or 0) for item in research_rounds),
        "max_research_round_count": max((int(item.get("round_count", 0) or 0) for item in research_rounds), default=0),
        "gaps_remaining": gaps_remaining,
        "source_class_breakdown": source_class_breakdown,
        "placeholder_count": placeholder_count,
        "mermaid_count": mermaid_block_count,
        "image_count": image_block_count,
        "interactive_block_count": interactive_block_count,
        "asset_count": asset_count,
        "asset_summary": asset_summary,
        "practice_count": practice_count,
        "coverage_score": round(sum(coverage_scores) / max(1, len(coverage_scores)), 4) if coverage_scores else 0.0,
        "quality_score": round(sum(quality_scores) / max(1, len(quality_scores)), 4) if quality_scores else 0.0,
        "quality_summary": {
            "avg_coverage_score": round(sum(coverage_scores) / max(1, len(coverage_scores)), 4) if coverage_scores else 0.0,
            "avg_quality_score": round(sum(quality_scores) / max(1, len(quality_scores)), 4) if quality_scores else 0.0,
            "asset_count": asset_count,
            "repaired_chapter_count": repaired_chapter_count,
            "mermaid_count": mermaid_block_count,
            "image_count": image_block_count,
            "interactive_block_count": interactive_block_count,
            "practice_count": practice_count,
        },
        "word_count": count_words(final_markdown),
        "final_word_count": count_words(final_markdown),
        "docgen_total_tokens": token_summary.total_tokens,
        "docgen_tokens_by_task_type": token_summary.tokens_by_task_type,
        "docgen_tokens_by_model": token_summary.tokens_by_model,
        **_lane_llm_rollup(token_summary),
        "slowest_research_chapters_top_k": [item.model_dump() for item in research_items],
        "slowest_draft_chapters_top_k": [item.model_dump() for item in draft_items],
    }


def build_kg_lane_summary(
    state: Mapping[str, Any],
    *,
    token_summary: DigestTokenSummary,
    status: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Create a KG lane summary payload."""

    resolved_status = _resolve_status(state, status=status, error_message=error_message)
    resolved_error = _resolve_error_message(state, error_message=error_message)
    extract_tokens = int(token_summary.tokens_by_node.get("extract", 0))
    resolve_tokens = int(token_summary.tokens_by_node.get("resolve_nodes", 0)) + int(
        token_summary.tokens_by_node.get("resolve_edges", 0)
    )
    return {
        "status": resolved_status,
        "error_message": resolved_error,
        "chunk_count": len(state.get("chunk_ids", [])),
        "cluster_count": len(state.get("clustered_candidates", [])),
        "resolved_node_count": int(state.get("resolved_node_count", 0)),
        "active_node_count": int(state.get("active_node_count", 0)),
        "active_edge_count": int(state.get("active_edge_count", 0)),
        "workflow_elapsed_ms": int(state.get("workflow_elapsed_ms", 0)),
        "acquire_lock_ms": int(state.get("acquire_lock_ms", 0)),
        "prepare_ms": int(state.get("prepare_ms", 0)),
        "extract_ms": int(state.get("extract_ms", 0)),
        "cluster_ms": int(state.get("cluster_ms", 0)),
        "resolve_nodes_ms": int(state.get("resolve_nodes_ms", 0)),
        "resolve_edges_ms": int(state.get("resolve_edges_ms", 0)),
        "impact_ms": int(state.get("impact_ms", 0)),
        "finalize_ms": int(state.get("finalize_ms", 0)),
        "resolution_index_ms": int(state.get("resolution_index_ms", 0)),
        "candidate_embedding_ms": int(state.get("candidate_embedding_ms", 0)),
        "node_persist_ms": int(state.get("node_persist_ms", 0)),
        "edge_persist_ms": int(state.get("edge_persist_ms", 0)),
        "fast_path_chunk_count": int(state.get("fast_path_chunk_count", 0)),
        "llm_extract_chunk_count": int(state.get("llm_extract_chunk_count", 0)),
        "success_chunk_count": int(state.get("success_chunk_count", 0)),
        "failed_chunk_count": int(state.get("failed_chunk_count", 0)),
        "no_match_count": int(state.get("no_match_count", 0)),
        "secondary_no_match_count": int(state.get("secondary_no_match_count", 0)),
        "unresolved_endpoint_count": int(state.get("unresolved_endpoint_count", 0)),
        "extract_total_tokens": extract_tokens,
        "resolve_total_tokens": resolve_tokens,
        **_lane_llm_rollup(token_summary),
        "slowest_chunks_top_k": [item.model_dump() for item in build_slow_items(state.get("slowest_chunks", []))],
    }


def build_curriculum_lane_summary(
    state: Mapping[str, Any],
    *,
    token_summary: DigestTokenSummary,
    status: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Create a curriculum lane summary payload."""

    resolved_status = _resolve_status(state, status=status, error_message=error_message)
    resolved_error = _resolve_error_message(state, error_message=error_message)
    return {
        "status": resolved_status,
        "error_message": resolved_error,
        "curriculum_ready": bool(state.get("curriculum_ready")),
        "derived_unit_count": len(state.get("derived_unit_ids", [])),
        "created_unit_count": len(state.get("created_unit_ids", [])),
        "updated_unit_count": len(state.get("updated_unit_ids", [])),
        "workflow_elapsed_ms": int(state.get("workflow_elapsed_ms", 0)),
        "derive_units_ms": int(state.get("derive_units_ms", 0)),
        "theme_tree_ms": int(state.get("theme_tree_ms", 0)),
        "prereq_dag_ms": int(state.get("prereq_dag_ms", 0)),
        "finalize_ms": int(state.get("finalize_ms", 0)),
        "subgraph_load_ms": int(state.get("subgraph_load_ms", 0)),
        "candidate_build_ms": int(state.get("candidate_build_ms", 0)),
        "unit_naming_ms": int(state.get("unit_naming_ms", 0)),
        "unit_persist_ms": int(state.get("unit_persist_ms", 0)),
        "rule_named_unit_count": int(state.get("rule_named_unit_count", 0)),
        "llm_named_unit_count": int(state.get("llm_named_unit_count", 0)),
        "fallback_named_unit_count": int(state.get("fallback_named_unit_count", 0)),
        "unit_naming_parallelism": int(state.get("unit_naming_parallelism", 0)),
        "unit_naming_total_tokens": int(token_summary.tokens_by_node.get("derive_units", token_summary.total_tokens)),
        "unit_naming_tokens_by_model": token_summary.tokens_by_model,
        **_lane_llm_rollup(token_summary),
        "slowest_unit_namings_top_k": [
            item.model_dump() for item in build_slow_items(state.get("slowest_unit_namings", []))
        ],
    }


# ── Private helpers ────────────────────────────────────────────────


def _top_k(value: int | None = None) -> int:
    from app.shared.infra.config import get_settings

    if value is not None:
        return max(1, int(value))
    return max(1, int(get_settings().digest_timing_top_k))


def _resolve_status(
    state: Mapping[str, Any],
    *,
    status: str | None,
    error_message: str | None,
) -> str:
    if status:
        return status
    if error_message or state.get("error"):
        return "failed"
    if not state:
        return "ok"
    return "ok"


def _resolve_error_message(state: Mapping[str, Any], *, error_message: str | None) -> str | None:
    resolved = error_message or str(state.get("error", "")).strip()
    return resolved or None


def _default_lane_status(state: Mapping[str, Any], *, final_status: str) -> str | None:
    if state:
        return None
    if final_status == "completed":
        return "ok"
    return "skipped"


def _lane_llm_rollup(token_summary: DigestTokenSummary) -> dict[str, Any]:
    return {
        "llm_total_calls": token_summary.total_calls,
        "failed_llm_call_count": token_summary.failed_call_count,
        "llm_total_latency_ms": token_summary.total_latency_ms,
        "llm_avg_latency_ms": token_summary.avg_latency_ms,
        "tokens_by_model": token_summary.tokens_by_model,
        "tokens_by_task_type": token_summary.tokens_by_task_type,
        "call_count_by_model": token_summary.call_count_by_model,
        "call_count_by_task_type": token_summary.call_count_by_task_type,
        "light_vs_heavy_model_mix": {
            "light_model_call_count": token_summary.light_model_call_count,
            "light_model_total_tokens": token_summary.light_model_total_tokens,
            "heavy_model_call_count": token_summary.heavy_model_call_count,
            "heavy_model_total_tokens": token_summary.heavy_model_total_tokens,
        },
        "task_type_mix_ratio": token_summary.task_type_mix_ratio,
        "model_mix_ratio": token_summary.model_mix_ratio,
    }


def _lane_step_items(lane: str, step_map: Mapping[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for step_name, elapsed_ms in step_map.items():
        elapsed = int(elapsed_ms or 0)
        if elapsed <= 0:
            continue
        items.append(
            {
                "item_id": f"{lane}.{step_name}",
                "title": f"{lane}.{step_name}",
                "elapsed_ms": elapsed,
                "lane": lane,
                "step": step_name,
            }
        )
    return items


def _sum_count_maps(items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for item in items:
        for key, value in item.items():
            normalized = str(key).strip()
            if not normalized:
                continue
            totals[normalized] = totals.get(normalized, 0) + int(value or 0)
    return {key: value for key, value in totals.items() if value > 0}
