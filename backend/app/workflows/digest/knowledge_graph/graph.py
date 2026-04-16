"""Digest knowledge-graph workflow graph and initial state."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.workflows.digest.knowledge_graph.nodes import (
    acquire_lock_node,
    analyze_impact_node,
    build_finalize_graph_node,
    cluster_node,
    extract_node,
    fail_node,
    prepare_node,
    resolve_edges_node,
    resolve_nodes_node,
)
from app.workflows.digest.knowledge_graph.lib.routes import route_after_lock, route_after_prepare, route_after_step
from app.workflows.digest.knowledge_graph.state import KGDigestState, KnowledgeDigestState

def build_kg_digest_graph() -> StateGraph:
    """Build the LangGraph workflow for digest graph construction."""

    workflow = StateGraph(KGDigestState)
    trace = workflow_tracer(workflow="digest.graph", lane="kg")
    workflow.add_node(
        "acquire_lock",
        trace.node(
            acquire_lock_node,
            name="acquire_lock",
            timing_field="acquire_lock_ms",
        ),
    )
    workflow.add_node(
        "prepare",
        trace.node(
            prepare_node,
            name="prepare",
            timing_field="prepare_ms",
        ),
    )
    workflow.add_node(
        "extract",
        trace.node(
            extract_node,
            name="extract",
            timing_field="extract_ms",
        ),
    )
    workflow.add_node(
        "cluster",
        trace.node(
            cluster_node,
            name="cluster",
            timing_field="cluster_ms",
        ),
    )
    workflow.add_node(
        "resolve_nodes",
        trace.node(
            resolve_nodes_node,
            name="resolve_nodes",
            timing_field="resolve_nodes_ms",
        ),
    )
    workflow.add_node(
        "resolve_edges",
        trace.node(
            resolve_edges_node,
            name="resolve_edges",
            timing_field="resolve_edges_ms",
        ),
    )
    workflow.add_node(
        "analyze_impact",
        trace.node(
            analyze_impact_node,
            name="analyze_impact",
            timing_field="impact_ms",
        ),
    )
    workflow.add_node(
        "finalize_graph",
        trace.node(
            build_finalize_graph_node(),
            name="finalize_graph",
            timing_field="finalize_ms",
        ),
    )
    workflow.add_node(
        "fail",
        trace.node(
            fail_node,
            name="fail",
        ),
    )

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


build_knowledge_digest_graph = build_kg_digest_graph


def create_graph_digest_initial_state(
    *,
    subject: str,
    file_ids: list[int],
    job_id: int,
    build_session_id: str | None = None,
    user_prompt: str | None = None,
    doc_chapter_metadatas: list[dict[str, object]] | None = None,
) -> KnowledgeDigestState:
    """Create the initial state for digest graph building."""

    return {
        "subject": subject,
        "file_ids": file_ids,
        "job_id": job_id,
        "build_session_id": build_session_id or "",
        "user_prompt": user_prompt,
        "doc_chapter_metadatas": list(doc_chapter_metadatas or []),
        "shared_inputs": None,
        "chunk_ids": [],
        "chunk_uid_to_chunk_id": {},
        "chunk_id_to_chunk_uid": {},
        "candidates": [],
        "all_candidate_edges": [],
        "clustered_candidates": [],
        "candidate_lookup_to_cluster_id": {},
        "candidate_lookup_to_resolved_node_id": {},
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
    "build_kg_digest_graph",
    "build_knowledge_digest_graph",
    "create_graph_digest_initial_state",
]

