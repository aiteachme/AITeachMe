"""DocGen lane reporting helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.workflows.digest.common.metrics import (
    DigestTokenSummary,
    build_lane_llm_rollup,
    build_slow_items,
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
    previous_chapter_materials = list(state.get("chapter_materials", []))
    chapter_drafts = list(state.get("chapter_drafts", []))
    enhanced_chapter_drafts = list(state.get("enhanced_chapter_drafts", []))
    chapter_metadatas = list(state.get("chapter_metadatas", []))
    research_traces = list(state.get("research_traces", []))
    research_records = previous_chapter_materials or chapter_metadatas or enhanced_chapter_drafts or chapter_drafts
    document_context = dict(state.get("document_context", {}) or {})
    chapter_count = max(
        len(chapter_metadatas),
        len(enhanced_chapter_drafts),
        len(chapter_drafts),
        len(previous_chapter_materials),
    )
    research_items = build_slow_items(
        state.get("slowest_research_chapters")
        or [
            {
                "item_id": f"chapter_{material.get('chapter_index', index)}",
                "title": str(material.get("title", "")),
                "elapsed_ms": int(material.get("research_ms", 0)),
                "source_count": len(material.get("sources", [])),
                "local_hits": _research_metric(material, "local_hits"),
                "web_hits": _research_metric(material, "web_hits"),
            }
            for index, material in enumerate(research_records, start=1)
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
        for url in [
            *state.get("research_sources", []),
            *[
                source
                for chapter in chapter_metadatas
                for source in chapter.get("sources", [])
            ],
            *[
                source
                for chapter in enhanced_chapter_drafts
                for source in chapter.get("sources", [])
            ],
        ]
        if str(url).strip()
    ]
    total_sources = len(dict.fromkeys(source_urls))
    placeholder_count = sum(int(chapter.get("placeholder_count", 0)) for chapter in chapter_drafts)
    local_hit_count = sum(_research_metric(chapter, "local_hits") for chapter in research_records)
    web_hit_count = sum(_research_metric(chapter, "web_hits") for chapter in research_records)
    fallback_chapter_count = sum(
        1 for chapter in research_records if bool(chapter.get("fallback_used", False))
    )
    curated_source_count = sum(int(chapter.get("curated_source_count", 0) or 0) for chapter in research_records)
    trusted_source_count = sum(int(chapter.get("trusted_source_count", 0) or 0) for chapter in research_records)
    retrieval_profiles = sorted(
        {
            str(chapter.get("retrieval_profile") or "").strip()
            for chapter in research_records
            if str(chapter.get("retrieval_profile") or "").strip()
        }
    )
    if not retrieval_profiles and str(state.get("retrieval_profile") or "").strip():
        retrieval_profiles = [str(state.get("retrieval_profile") or "").strip()]
    teaching_actions = sorted(
        {
            str(item.get("teaching_action") or "").strip()
            for item in [*research_records, *chapter_drafts]
            if str(item.get("teaching_action") or "").strip()
        }
    )
    if not teaching_actions and str(state.get("teaching_action") or "").strip():
        teaching_actions = [str(state.get("teaching_action") or "").strip()]
    planned_query_count = (
        sum(len(task.get("retrieval_queries", []) or []) for task in list(state.get("chapter_tasks", []) or []))
        or sum(len(chapter.get("planned_queries", []) or []) for chapter in research_records)
    )
    executed_query_count = (
        sum(len(trace.get("executed_queries", []) or []) for trace in research_traces)
        or sum(len(chapter.get("executed_queries", []) or []) for chapter in research_records)
    )
    read_url_count = (
        sum(int((trace.get("budget_used") or {}).get("read_url_count", 0) or 0) for trace in research_traces)
        or sum(_research_metric(chapter, "read_url_count") for chapter in research_records)
    )
    research_document_count = (
        sum(int((trace.get("budget_used") or {}).get("document_count", 0) or 0) for trace in research_traces)
        or sum(_research_metric(chapter, "document_count") for chapter in research_records)
    )
    purify_chapter_count = sum(1 for chapter in research_records if bool(chapter.get("purify_used", False)))
    retriever_names = sorted(
        {
            str(retriever_name)
            for chapter in research_records
            for retriever_name in dict(chapter.get("retriever_stats", {}) or {}).keys()
            if str(retriever_name).strip()
        }
    )
    active_retriever_names = sorted(
        {
            str(retriever_name).strip()
            for chapter in research_records
            for retriever_name in list(chapter.get("active_retrievers", []) or [])
            if str(retriever_name).strip()
        }
    )
    configured_retriever_names = sorted(
        {
            str(retriever_name).strip()
            for chapter in research_records
            for retriever_name in list(chapter.get("configured_retrievers", []) or [])
            if str(retriever_name).strip()
        }
    )
    applied_retrieval_profiles = sorted(
        {
            str(chapter.get("applied_retrieval_profile") or "").strip()
            for chapter in research_records
            if str(chapter.get("applied_retrieval_profile") or "").strip()
        }
    )
    requested_profiles = sorted(
        {
            str(chapter.get("requested_profile") or chapter.get("requested_retrieval_profile") or "").strip()
            for chapter in research_records
            if str(chapter.get("requested_profile") or chapter.get("requested_retrieval_profile") or "").strip()
        }
    )
    applied_profiles = sorted(
        {
            str(chapter.get("applied_profile") or chapter.get("applied_retrieval_profile") or "").strip()
            for chapter in research_records
            if str(chapter.get("applied_profile") or chapter.get("applied_retrieval_profile") or "").strip()
        }
    )
    title_by_chapter = {
        int(chapter.get("chapter_index", 0) or 0): str(chapter.get("resolved_title") or chapter.get("title") or "")
        for chapter in research_records
    }
    research_rounds = _research_round_summaries(research_traces, title_by_chapter=title_by_chapter) or [
        {
            "chapter_index": int(chapter.get("chapter_index", 0) or 0),
            "title": str(chapter.get("resolved_title") or chapter.get("title") or ""),
            "round_count": int(chapter.get("research_round_count", 0) or len(chapter.get("research_rounds", []) or [])),
        }
        for chapter in research_records
    ]
    gaps_remaining = sorted(
        {
            str(gap).strip()
            for trace in research_traces
            for gap in list(trace.get("gap_notes", []) or [])
            if str(gap).strip()
        }
    )[:12] or sorted(
        {
            str(gap).strip()
            for chapter in research_records
            for gap in list(chapter.get("gaps_remaining", []) or [])
            if str(gap).strip()
        }
    )[:12]
    source_class_breakdown = _sum_count_maps(
        [
            dict(round_item.get("source_class_breakdown", {}) or {})
            for trace in research_traces
            for round_item in list(trace.get("rounds", []) or [])
        ]
        or [dict(chapter.get("source_class_breakdown", {}) or {}) for chapter in research_records]
    )
    asset_items = [
        asset
        for manifest in list(state.get("asset_manifests", []) or [])
        for asset in list((manifest or {}).get("assets") or [])
    ]
    practice_items = [
        question
        for manifest in list(state.get("practice_manifests", []) or [])
        for question in list((manifest or {}).get("questions") or [])
    ]
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
            int(str(chapter.get("markdown") or "").count("建议配图"))
            + int(str(chapter.get("markdown") or "").count("配图建议占位"))
            for chapter in chapter_metadatas
        )
    asset_summary = {
        "mermaid": mermaid_block_count or sum(1 for asset in asset_items if asset.get("kind") == "mermaid"),
        "image": image_block_count or sum(1 for asset in asset_items if asset.get("kind") == "image"),
        "animation": int(
            ((state.get("asset_summary") or {}) if isinstance(state.get("asset_summary"), Mapping) else {}).get(
                "animation", 0
            )
            or 0
        ),
    }
    asset_count = int(state.get("asset_count", 0) or 0) or sum(asset_summary.values())
    practice_count = int(state.get("practice_count", 0) or 0) or sum(
        int(chapter.get("practice_count", 0) or 0)
        for chapter in chapter_metadatas
    ) or len(practice_items) or len(state.get("exam_questions", []))

    def _quality_mapping(chapter: Mapping[str, Any]) -> Mapping[str, Any]:
        nested = chapter.get("quality_signals")
        return nested if isinstance(nested, Mapping) else chapter

    coverage_scores = [
        float(_quality_mapping(chapter).get("coverage_score", 0.0) or 0.0)
        for chapter in [*chapter_drafts, *enhanced_chapter_drafts, *research_records]
        if float(_quality_mapping(chapter).get("coverage_score", 0.0) or 0.0) > 0
    ] + [
        float(trace.get("coverage_score", 0.0) or 0.0)
        for trace in research_traces
        if float(trace.get("coverage_score", 0.0) or 0.0) > 0
    ]
    quality_scores = [
        float(_quality_mapping(chapter).get("quality_score", 0.0) or 0.0)
        for chapter in [*chapter_drafts, *enhanced_chapter_drafts]
        if float(_quality_mapping(chapter).get("quality_score", 0.0) or 0.0) > 0
    ]
    repaired_chapter_count = sum(
        1
        for chapter in [*chapter_drafts, *enhanced_chapter_drafts]
        if bool(_quality_mapping(chapter).get("rewrite_used", False) or chapter.get("repair_applied", False))
    )
    return {
        "status": resolved_status,
        "error_message": resolved_error,
        "planner_session_id": str(state.get("planner_session_id", "") or ""),
        "confirmed_plan_id": str(state.get("confirmed_plan_id", "") or ""),
        "digest_mode": str(state.get("digest_mode", "") or ""),
        "source_strategy": str(document_context.get("source_strategy", "") or ""),
        "retrieval_profiles": retrieval_profiles,
        "teaching_actions": teaching_actions,
        "chapter_count": chapter_count,
        "workflow_elapsed_ms": int(state.get("workflow_elapsed_ms", 0)),
        "load_ms": int(state.get("load_ms", 0)),
        "prepare_ms": int(state.get("prepare_ms", 0)),
        "intent_core_ms": int(state.get("intent_core_ms", 0)),
        "title_lock_ms": int(state.get("title_lock_ms", 0)),
        "planner_ms": int(state.get("planner_ms", 0)),
        "seed_backbone_ms": int(state.get("seed_backbone_ms", 0)),
        "backbone_ms": int(state.get("backbone_ms", 0)),
        "chapter_prepare_ms": int(state.get("chapter_prepare_ms", 0)),
        "assemble_tasks_ms": int(state.get("assemble_tasks_ms", 0)),
        "research_ms": int(state.get("research_ms", 0)),
        "draft_ms": int(state.get("draft_ms", 0)),
        "enrich_ms": int(state.get("enrich_ms", 0) or state.get("enhance_ms", 0) or 0),
        "enhance_ms": int(state.get("enhance_ms", 0)),
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
        **build_lane_llm_rollup(token_summary),
        "slowest_research_chapters_top_k": [item.model_dump() for item in research_items],
        "slowest_draft_chapters_top_k": [item.model_dump() for item in draft_items],
    }


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


def _research_metric(chapter: Mapping[str, Any], key: str) -> int:
    scope = chapter.get("source_scope")
    if isinstance(scope, Mapping) and key in scope:
        return int(scope.get(key, 0) or 0)
    return int(chapter.get(key, 0) or 0)


def _research_round_summaries(
    traces: Sequence[Mapping[str, Any]],
    *,
    title_by_chapter: Mapping[int, str],
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for trace in traces:
        chapter_index = int(trace.get("chapter_index", 0) or 0)
        if chapter_index <= 0:
            continue
        summaries.append(
            {
                "chapter_index": chapter_index,
                "title": str(title_by_chapter.get(chapter_index) or ""),
                "round_count": len(list(trace.get("rounds", []) or [])),
            }
        )
    return summaries


def _sum_count_maps(items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    totals: dict[str, int] = {}
    for item in items:
        for key, value in item.items():
            normalized = str(key).strip()
            if not normalized:
                continue
            totals[normalized] = totals.get(normalized, 0) + int(value or 0)
    return {key: value for key, value in totals.items() if value > 0}


__all__ = ["build_docgen_lane_summary"]
