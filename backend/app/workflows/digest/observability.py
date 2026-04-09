"""Helpers for digest timing and token observability."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, Field
import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.tools.builtin.markdown_processing import count_words
from app.shared.infra.tracing import get_tracker
from app.workflows.common.observability import wrap_workflow_node

logger = structlog.get_logger(__name__)


class SlowItemTiming(BaseModel):
    """A single slow item entry."""

    item_id: str
    title: str = ""
    elapsed_ms: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class DigestModelUsageSummary(BaseModel):
    """Model-level token usage summary."""

    call_count: int = 0
    failed_call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0


class DigestTokenSummary(BaseModel):
    """Token summary for a workflow build or lane."""

    total_calls: int = 0
    failed_call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0
    avg_latency_ms: float = 0.0
    tokens_by_model: dict[str, int] = Field(default_factory=dict)
    tokens_by_task_type: dict[str, int] = Field(default_factory=dict)
    tokens_by_lane: dict[str, int] = Field(default_factory=dict)
    tokens_by_node: dict[str, int] = Field(default_factory=dict)
    call_count_by_model: dict[str, int] = Field(default_factory=dict)
    call_count_by_task_type: dict[str, int] = Field(default_factory=dict)
    call_count_by_lane: dict[str, int] = Field(default_factory=dict)
    call_count_by_node: dict[str, int] = Field(default_factory=dict)
    model_usage: dict[str, DigestModelUsageSummary] = Field(default_factory=dict)
    light_model_call_count: int = 0
    light_model_total_tokens: int = 0
    heavy_model_call_count: int = 0
    heavy_model_total_tokens: int = 0
    light_task_call_count: int = 0
    light_task_total_tokens: int = 0
    heavy_task_call_count: int = 0
    heavy_task_total_tokens: int = 0
    model_mix_ratio: dict[str, float] = Field(default_factory=dict)
    task_type_mix_ratio: dict[str, float] = Field(default_factory=dict)


class DigestTimingReport(BaseModel):
    """Unified digest timing and token report."""

    status: str = "completed"
    elapsed_ms: int = 0
    unified: dict[str, Any] = Field(default_factory=dict)
    docgen: dict[str, Any] = Field(default_factory=dict)
    kg: dict[str, Any] = Field(default_factory=dict)
    curriculum: dict[str, Any] = Field(default_factory=dict)
    llm: DigestTokenSummary = Field(default_factory=DigestTokenSummary)
    top_slowest_steps: list[SlowItemTiming] = Field(default_factory=list)


def build_token_summary(
    *,
    build_session_id: str | None = None,
    subject: str | None = None,
    workflow: str | None = None,
    lane: str | None = None,
    node: str | None = None,
) -> DigestTokenSummary:
    """Build a typed token summary from the global tracker."""

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
    scraped_url_count = sum(int(chapter.get("scraped_url_count", 0) or 0) for chapter in chapter_materials)
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
        "planned_query_count": planned_query_count,
        "executed_query_count": executed_query_count,
        "scraped_url_count": scraped_url_count,
        "research_document_count": research_document_count,
        "purify_chapter_count": purify_chapter_count,
        "placeholder_count": placeholder_count,
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


def wrap_digest_node(
    handler: Callable[[Any], Awaitable[dict[str, Any]]],
    *,
    workflow_name: str,
    lane: str,
    node_name: str,
    timing_field: str | None = None,
) -> Callable[[Any], Awaitable[dict[str, Any]]]:
    """Wrap a digest node with the shared lightweight LangSmith wrapper."""

    return wrap_workflow_node(
        handler,
        workflow_name=workflow_name,
        lane=lane,
        node_name=node_name,
        timing_field=timing_field,
    )


def _top_k(value: int | None = None) -> int:
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
