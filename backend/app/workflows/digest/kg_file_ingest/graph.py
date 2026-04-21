"""Digest knowledge-graph workflow graph and initial state."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.workflows.digest.kg_file_ingest.lib.routes import (
    route_after_lock_for_trace,
    route_after_prepare_for_trace,
    route_after_step_for_trace,
)
from app.workflows.digest.kg_file_ingest.nodes import (
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
from app.workflows.digest.kg_file_ingest.state import KGDigestState, KnowledgeDigestState

RUN_NAME_KG_FILE_INGEST = "知识图谱摄取：解析文件并构建图谱"


def build_kg_digest_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the LangGraph workflow for digest graph construction."""

    workflow = StateGraph(KGDigestState)
    trace = workflow_tracer(context=context, lane="kg_file_ingest")
    workflow.add_node(
        "acquire_lock",
        trace.node(
            acquire_lock_node,
            name="获取构建锁",
            timing_field="acquire_lock_ms",
        ),
    )
    workflow.add_node(
        "prepare",
        trace.node(
            prepare_node,
            name="准备分块与上下文",
            timing_field="prepare_ms",
        ),
    )
    workflow.add_node(
        "extract",
        trace.node(
            extract_node,
            name="抽取候选节点与关系",
            timing_field="extract_ms",
        ),
    )
    workflow.add_node(
        "cluster",
        trace.node(
            cluster_node,
            name="聚类候选知识点",
            timing_field="cluster_ms",
        ),
    )
    workflow.add_node(
        "resolve_nodes",
        trace.node(
            resolve_nodes_node,
            name="解析知识点落库",
            timing_field="resolve_nodes_ms",
        ),
    )
    workflow.add_node(
        "resolve_edges",
        trace.node(
            resolve_edges_node,
            name="解析关系落库",
            timing_field="resolve_edges_ms",
        ),
    )
    workflow.add_node(
        "analyze_impact",
        trace.node(
            analyze_impact_node,
            name="分析图谱影响面",
            timing_field="impact_ms",
        ),
    )
    workflow.add_node(
        "finalize_graph",
        trace.node(
            build_finalize_graph_node(),
            name="收口图谱构建结果",
            timing_field="finalize_ms",
        ),
    )
    workflow.add_node(
        "fail",
        trace.node(
            fail_node,
            name="记录失败结果",
        ),
    )

    workflow.set_entry_point("acquire_lock")
    workflow.add_conditional_edges(
        "acquire_lock",
        route_after_lock_for_trace,
        {
            "prepare": "prepare",
            "fail": "fail",
        },
    )
    workflow.add_conditional_edges(
        "prepare",
        route_after_prepare_for_trace,
        {
            "extract": "extract",
            "finalize_graph": "finalize_graph",
            "fail": "fail",
        },
    )
    workflow.add_conditional_edges(
        "extract",
        route_after_step_for_trace,
        {
            "continue": "cluster",
            "fail": "fail",
        },
    )
    workflow.add_conditional_edges(
        "cluster",
        route_after_step_for_trace,
        {
            "continue": "resolve_nodes",
            "fail": "fail",
        },
    )
    workflow.add_conditional_edges(
        "resolve_nodes",
        route_after_step_for_trace,
        {
            "continue": "resolve_edges",
            "fail": "fail",
        },
    )
    workflow.add_conditional_edges(
        "resolve_edges",
        route_after_step_for_trace,
        {
            "continue": "analyze_impact",
            "fail": "fail",
        },
    )
    workflow.add_conditional_edges(
        "analyze_impact",
        route_after_step_for_trace,
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


def get_langgraph_dev_kg_file_ingest_graph() -> StateGraph:
    return build_kg_digest_graph(context=create_langgraph_dev_context("digest.kg_file_ingest.langgraph_dev"))


__all__ = [
    "RUN_NAME_KG_FILE_INGEST",
    "build_kg_digest_graph",
    "create_graph_digest_initial_state",
    "get_langgraph_dev_kg_file_ingest_graph",
]
