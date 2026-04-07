"""Helpers for digest timing and token observability."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from time import perf_counter
from typing import Any

from pydantic import BaseModel, Field
import structlog

from app.shared.infra.config import get_settings
from app.shared.infra.tracing import get_tracker, llm_trace_scope

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
    docs: dict[str, Any] = Field(default_factory=dict)
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


def build_docs_lane_summary(
    state: Mapping[str, Any],
    *,
    token_summary: DigestTokenSummary,
    status: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any]:
    """Create a docs lane summary payload."""

    resolved_status = _resolve_status(state, status=status, error_message=error_message)
    resolved_error = _resolve_error_message(state, error_message=error_message)
    chapter_count = max(
        len(state.get("chapter_metadatas", [])),
        len(state.get("chapter_reviews", [])),
        len(state.get("chapter_drafts", [])),
    )
    draft_items = build_slow_items(
        state.get("slowest_draft_chapters")
        or [
            {
                "item_id": f"chapter_{draft.get('chapter_index', index)}",
                "title": str(draft.get("title", "")),
                "elapsed_ms": int(draft.get("draft_ms", 0)),
            }
            for index, draft in enumerate(state.get("chapter_drafts", []), start=1)
        ]
    )
    review_items = build_slow_items(
        state.get("slowest_review_chapters")
        or [
            {
                "item_id": f"chapter_{review.get('chapter_index', index)}",
                "title": str(review.get("title", "")),
                "elapsed_ms": int(review.get("review_ms", 0)),
            }
            for index, review in enumerate(state.get("chapter_reviews", []), start=1)
        ]
    )
    return {
        "status": resolved_status,
        "error_message": resolved_error,
        "chapter_count": chapter_count,
        "workflow_elapsed_ms": int(state.get("workflow_elapsed_ms", 0)),
        "load_ms": int(state.get("load_ms", 0)),
        "cleanse_ms": int(state.get("cleanse_ms", 0)),
        "outline_ms": int(state.get("outline_ms", 0)),
        "draft_ms": int(state.get("draft_ms", 0)),
        "review_ms": int(state.get("review_ms", 0)),
        "metadata_ms": int(state.get("metadata_ms", 0)),
        "finalize_ms": int(state.get("finalize_ms", 0)),
        "draft_avg_ms": round(int(state.get("draft_ms", 0)) / chapter_count, 2) if chapter_count else 0.0,
        "review_avg_ms": round(int(state.get("review_ms", 0)) / chapter_count, 2) if chapter_count else 0.0,
        "llm_calls_total": int(state.get("llm_calls_total", 0)),
        "llm_calls_skipped": int(state.get("llm_calls_skipped", 0)),
        "draft_available": bool(str(state.get("merged_markdown", "")).strip()),
        "staged_chapter_count": len(state.get("chapter_metadatas", [])),
        "published_doc_count": len(state.get("doc_ids", [])),
        "docs_total_tokens": token_summary.total_tokens,
        "docs_tokens_by_task_type": token_summary.tokens_by_task_type,
        "docs_tokens_by_model": token_summary.tokens_by_model,
        **_lane_llm_rollup(token_summary),
        "slowest_draft_chapters_top_k": [item.model_dump() for item in draft_items],
        "slowest_review_chapters_top_k": [item.model_dump() for item in review_items],
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
    docs_token_summary = build_token_summary(build_session_id=build_session_id, lane="docs")
    kg_token_summary = build_token_summary(build_session_id=build_session_id, lane="kg")
    curriculum_token_summary = build_token_summary(build_session_id=build_session_id, lane="curriculum")
    docs_summary = build_docs_lane_summary(
        doc_state,
        token_summary=docs_token_summary,
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
                "docs",
                {
                    "load": docs_summary.get("load_ms", 0),
                    "cleanse": docs_summary.get("cleanse_ms", 0),
                    "outline": docs_summary.get("outline_ms", 0),
                    "draft": docs_summary.get("draft_ms", 0),
                    "review": docs_summary.get("review_ms", 0),
                    "metadata": docs_summary.get("metadata_ms", 0),
                    "finalize": docs_summary.get("finalize_ms", 0),
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
                "docs": docs_token_summary.total_tokens,
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
        docs=docs_summary,
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
    """Wrap a workflow node with trace context and generic timing logs."""

    async def wrapped(state: Any) -> dict[str, Any]:
        subject = str(state.get("subject", ""))
        build_session_id = str(state.get("build_session_id", ""))
        node_logger = logger.bind(
            workflow=workflow_name,
            lane=lane,
            node=node_name,
            subject=subject,
            build_session_id=build_session_id,
        )
        started_at = perf_counter()
        try:
            with llm_trace_scope(
                subject=subject,
                build_session_id=build_session_id,
                workflow=workflow_name,
                lane=lane,
                node=node_name,
            ):
                result = await handler(state)
        except Exception:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            node_logger.exception("digest_node_failed", elapsed_ms=elapsed_ms)
            raise

        elapsed_ms = int((perf_counter() - started_at) * 1000)
        if timing_field:
            result = {**result, timing_field: elapsed_ms}
        node_logger.info(
            "digest_node_completed",
            elapsed_ms=elapsed_ms,
            status="failed" if result.get("error") else "ok",
        )
        return result

    return wrapped


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
