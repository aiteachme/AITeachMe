"""Digest knowledge-graph workflow graph and initial state."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langgraph.graph import END, StateGraph

from app.workflows.digest.kg.finalize_nodes import build_finalize_graph_node, fail_node
from app.workflows.digest.kg.prepare_nodes import (
    acquire_lock_node,
    cluster_node,
    extract_node,
    prepare_node,
)
from app.workflows.digest.kg.resolve_nodes import (
    analyze_impact_node,
    resolve_edges_node,
    resolve_nodes_node,
)
from app.workflows.digest.kg.routes import route_after_lock, route_after_prepare, route_after_step
from app.workflows.digest.kg.state import KGDigestState

CurriculumTrigger = Callable[..., Awaitable[None]]


async def _noop_curriculum_trigger(**_: object) -> None:
    return None


def build_kg_digest_graph(
    *,
    trigger_curriculum_derive: CurriculumTrigger | None = None,
) -> StateGraph:
    """Build the LangGraph workflow for digest graph construction."""

    workflow = StateGraph(KGDigestState)
    workflow.add_node("acquire_lock", acquire_lock_node)
    workflow.add_node("prepare", prepare_node)
    workflow.add_node("extract", extract_node)
    workflow.add_node("cluster", cluster_node)
    workflow.add_node("resolve_nodes", resolve_nodes_node)
    workflow.add_node("resolve_edges", resolve_edges_node)
    workflow.add_node("analyze_impact", analyze_impact_node)
    workflow.add_node(
        "finalize_graph",
        build_finalize_graph_node(
            trigger_curriculum_derive=trigger_curriculum_derive or _noop_curriculum_trigger,
        ),
    )
    workflow.add_node("fail", fail_node)

    workflow.set_entry_point("acquire_lock")
    workflow.add_conditional_edges(
        "acquire_lock",
        route_after_lock,
        {
            "prepare": "prepare",
            "fail": "fail",
        },
    )
    workflow.add_conditional_edges(
        "prepare",
        route_after_prepare,
        {
            "extract": "extract",
            "finalize_graph": "finalize_graph",
            "fail": "fail",
        },
    )
    workflow.add_conditional_edges(
        "extract",
        route_after_step,
        {
            "continue": "cluster",
            "fail": "fail",
        },
    )
    workflow.add_conditional_edges(
        "cluster",
        route_after_step,
        {
            "continue": "resolve_nodes",
            "fail": "fail",
        },
    )
    workflow.add_conditional_edges(
        "resolve_nodes",
        route_after_step,
        {
            "continue": "resolve_edges",
            "fail": "fail",
        },
    )
    workflow.add_conditional_edges(
        "resolve_edges",
        route_after_step,
        {
            "continue": "analyze_impact",
            "fail": "fail",
        },
    )
    workflow.add_conditional_edges(
        "analyze_impact",
        route_after_step,
        {
            "continue": "finalize_graph",
            "fail": "fail",
        },
    )
    workflow.add_edge("finalize_graph", END)
    workflow.add_edge("fail", END)
    return workflow


def create_graph_digest_initial_state(
    *,
    subject: str,
    file_ids: list[int],
    job_id: int,
    build_session_id: str | None = None,
) -> KGDigestState:
    """Create the initial state for digest graph building."""

    return {
        "subject": subject,
        "file_ids": file_ids,
        "job_id": job_id,
        "build_session_id": build_session_id or "",
        "shared_inputs": None,
        "chunk_ids": [],
        "chunk_uid_to_chunk_id": {},
        "chunk_id_to_chunk_uid": {},
        "candidates": [],
        "all_candidate_edges": [],
        "clustered_candidates": [],
        "candidate_name_to_cluster_id": {},
        "candidate_name_to_resolved_node_id": {},
        "cluster_id_to_resolved_node_id": {},
        "new_node_ids": [],
        "updated_node_ids": [],
        "merged_node_ids": [],
        "new_edge_ids": [],
        "updated_edge_ids": [],
        "impact_set": None,
        "topic_anchor_snapshot": None,
        "lock_acquired": False,
        "error": None,
    }


__all__ = [
    "CurriculumTrigger",
    "build_kg_digest_graph",
    "create_graph_digest_initial_state",
]
