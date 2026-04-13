"""Unified digest timing report builder."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.shared.infra.tracing import get_tracker

from .models import DigestTimingReport, DigestTokenSummary
from .lane_summaries import (
    build_docgen_lane_summary,
    build_kg_lane_summary,
    build_curriculum_lane_summary,
    build_slow_items,
    _default_lane_status,
    _lane_step_items,
)


def build_token_summary(
    *,
    build_session_id: str | None = None,
    subject: str | None = None,
    workflow: str | None = None,
    lane: str | None = None,
    node: str | None = None,
) -> DigestTokenSummary:
    """Build a typed token summary from the global tracker."""

    from app.shared.infra.config import get_settings

    if not get_settings().digest_token_summary_enabled:
        return DigestTokenSummary()
    raw_summary = get_tracker().get_summary(
        build_session_id=build_session_id,
        subject=subject,
        workflow=workflow,
        lane=lane,
        node=node,
    )
    return DigestTokenSummary.model_validate(raw_summary)


def build_unified_timing_report(
    *,
    final_state: Mapping[str, Any],
    status: str,
    elapsed_ms: int,
    llm_summary: DigestTokenSummary,
) -> DigestTimingReport:
    """Create the final unified digest timing report."""

    doc_state = final_state.get("doc_state", {}) or {}
    kg_state = final_state.get("kg_state", {}) or {}
    curriculum_state = final_state.get("curriculum_state", {}) or {}
    unified_steps = {
        "prepare_shared": int(final_state.get("shared_prepare_ms", 0)),
        "parallel_lanes": int(final_state.get("parallel_lanes_ms", 0)),
        "derive_curriculum": int(final_state.get("curriculum_ms", 0)),
        "publish_outputs": int(final_state.get("publish_ms", 0)),
        "cleanup": int(final_state.get("cleanup_ms", 0)),
    }
    build_session_id = str(final_state.get("build_session_id", "")) or None
    docgen_token_summary = build_token_summary(build_session_id=build_session_id, lane="docgen")
    kg_token_summary = build_token_summary(build_session_id=build_session_id, lane="kg")
    curriculum_token_summary = build_token_summary(build_session_id=build_session_id, lane="curriculum")
    docgen_summary = build_docgen_lane_summary(
        doc_state,
        token_summary=docgen_token_summary,
        status=_default_lane_status(doc_state, final_status=status),
    )
    kg_summary = build_kg_lane_summary(
        kg_state,
        token_summary=kg_token_summary,
        status=_default_lane_status(kg_state, final_status=status),
    )
    curriculum_summary = build_curriculum_lane_summary(
        curriculum_state,
        token_summary=curriculum_token_summary,
        status=_default_lane_status(curriculum_state, final_status=status),
    )
    top_slowest_steps = build_slow_items(
        [
            *_lane_step_items("unified", unified_steps),
            *_lane_step_items(
                "docgen",
                {
                    "load": docgen_summary.get("load_ms", 0),
                    "planner": docgen_summary.get("planner_ms", 0),
                    "research": docgen_summary.get("research_ms", 0),
                    "draft": docgen_summary.get("draft_ms", 0),
                    "enrich": docgen_summary.get("enrich_ms", 0),
                    "examine": docgen_summary.get("examine_ms", 0),
                    "finalize": docgen_summary.get("finalize_ms", 0),
                },
            ),
            *_lane_step_items(
                "kg",
                {
                    "acquire_lock": kg_summary.get("acquire_lock_ms", 0),
                    "prepare": kg_summary.get("prepare_ms", 0),
                    "extract": kg_summary.get("extract_ms", 0),
                    "cluster": kg_summary.get("cluster_ms", 0),
                    "resolve_nodes": kg_summary.get("resolve_nodes_ms", 0),
                    "resolve_edges": kg_summary.get("resolve_edges_ms", 0),
                    "impact": kg_summary.get("impact_ms", 0),
                    "finalize": kg_summary.get("finalize_ms", 0),
                },
            ),
            *_lane_step_items(
                "curriculum",
                {
                    "derive_units": curriculum_summary.get("derive_units_ms", 0),
                    "theme_tree": curriculum_summary.get("theme_tree_ms", 0),
                    "prereq_dag": curriculum_summary.get("prereq_dag_ms", 0),
                    "finalize": curriculum_summary.get("finalize_ms", 0),
                },
            ),
        ]
    )
    return DigestTimingReport(
        status=status,
        elapsed_ms=elapsed_ms,
        unified={
            "status": status,
            "prepare_shared_ms": unified_steps["prepare_shared"],
            "parallel_lanes_ms": unified_steps["parallel_lanes"],
            "doc_lane_ms": int(final_state.get("doc_lane_ms", 0)),
            "kg_lane_ms": int(final_state.get("kg_lane_ms", 0)),
            "curriculum_ms": unified_steps["derive_curriculum"],
            "publish_ms": unified_steps["publish_outputs"],
            "cleanup_ms": unified_steps["cleanup"],
            "lane_total_tokens": {
                "docgen": docgen_token_summary.total_tokens,
                "kg": kg_token_summary.total_tokens,
                "curriculum": curriculum_token_summary.total_tokens,
                "unified_repair": int(llm_summary.tokens_by_lane.get("unified_repair", 0)),
            },
            "tokens_by_model": llm_summary.tokens_by_model,
            "tokens_by_task_type": llm_summary.tokens_by_task_type,
            "call_count_by_model": llm_summary.call_count_by_model,
            "call_count_by_task_type": llm_summary.call_count_by_task_type,
            "light_vs_heavy_model_mix": {
                "light_model_call_count": llm_summary.light_model_call_count,
                "light_model_total_tokens": llm_summary.light_model_total_tokens,
                "heavy_model_call_count": llm_summary.heavy_model_call_count,
                "heavy_model_total_tokens": llm_summary.heavy_model_total_tokens,
                "light_task_call_count": llm_summary.light_task_call_count,
                "light_task_total_tokens": llm_summary.light_task_total_tokens,
                "heavy_task_call_count": llm_summary.heavy_task_call_count,
                "heavy_task_total_tokens": llm_summary.heavy_task_total_tokens,
            },
        },
        docgen=docgen_summary,
        kg=kg_summary,
        curriculum=curriculum_summary,
        llm=llm_summary,
        top_slowest_steps=top_slowest_steps,
    )
