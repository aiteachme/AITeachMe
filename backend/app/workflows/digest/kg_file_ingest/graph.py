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
LEGACY_KG_FILE_INGEST_NOTE = (
    "legacy/debug-only：历史上用于直接从解析后的 Markdown 文件构建图谱。正式产品链路已经迁移到 "
    "docgen publish -> kg_docs_sync；这里只保留旧 workflow 壳和少量可复用抽取器，后续应迁移 extractor 后删除。"
)

NODE_ACQUIRE_LOCK = "acquire_lock"
NODE_PREPARE = "prepare"
NODE_EXTRACT = "extract"
NODE_CLUSTER = "cluster"
NODE_RESOLVE_NODES = "resolve_nodes"
NODE_RESOLVE_EDGES = "resolve_edges"
NODE_ANALYZE_IMPACT = "analyze_impact"
NODE_FINALIZE_GRAPH = "finalize_graph"
NODE_FAIL = "fail"

NODE_DISPLAY_NAMES = {
    NODE_ACQUIRE_LOCK: "获取构建锁",
    NODE_PREPARE: "准备分块与上下文",
    NODE_EXTRACT: "抽取候选节点与关系",
    NODE_CLUSTER: "聚类候选知识点",
    NODE_RESOLVE_NODES: "解析知识点落库",
    NODE_RESOLVE_EDGES: "解析关系落库",
    NODE_ANALYZE_IMPACT: "分析图谱影响面",
    NODE_FINALIZE_GRAPH: "收口图谱构建结果",
    NODE_FAIL: "记录失败结果",
}

NODE_TRACE_DETAILS: dict[str, dict[str, object]] = {
    NODE_ACQUIRE_LOCK: {
        "description": (
            f"{LEGACY_KG_FILE_INGEST_NOTE} 本节点尝试获取旧图谱构建 job 的互斥锁，避免同一学科并发写入旧 pending 结果。"
        ),
        "reads": ["knowledge_build_job"],
        "writes": ["knowledge_build_job.lock", "lock_acquired"],
        "input_keys": ["subject", "job_id", "build_session_id"],
        "output_keys": ["lock_acquired", "error"],
    },
    NODE_PREPARE: {
        "description": (
            f"{LEGACY_KG_FILE_INGEST_NOTE} 本节点读取原始文件解析结果，清洗 Markdown 并切成旧 file-ingest chunks。"
            "这条路径不再是正式图谱输入；新的调试应通过导入 KnowledgeDoc 后触发 kg_docs_sync。"
        ),
        "reads": ["raw_file", "parsed_markdown"],
        "writes": ["chunk_ids", "chunk_uid_to_chunk_id", "chunk_id_to_chunk_uid", "shared_inputs"],
        "input_keys": ["subject", "file_ids", "job_id", "user_prompt", "subject_context"],
        "output_keys": ["chunk_ids", "chunk_uid_to_chunk_id", "chunk_id_to_chunk_uid", "shared_inputs", "error"],
    },
    NODE_EXTRACT: {
        "description": (
            f"{LEGACY_KG_FILE_INGEST_NOTE} 本节点按 chunk 并发调用旧抽取器，产出候选知识点和候选关系。"
            "当前 docs-sync 仍复用其中的底层 extractor，但不应再从产品入口运行完整 file-ingest workflow。"
        ),
        "reads": ["chunk_ids", "shared_inputs", "subject_context"],
        "writes": ["candidates", "all_candidate_edges"],
        "input_keys": ["subject", "chunk_ids", "shared_inputs", "subject_context", "doc_chapter_metadatas"],
        "output_keys": ["candidates", "all_candidate_edges", "error"],
        "fanout": "internal_async_per_chunk",
    },
    NODE_CLUSTER: {
        "description": (
            f"{LEGACY_KG_FILE_INGEST_NOTE} 本节点把候选知识点按名称、别名和向量近似聚类，减少同义重复候选。"
        ),
        "reads": ["candidates"],
        "writes": ["clustered_candidates", "candidate_lookup_to_cluster_id"],
        "input_keys": ["subject", "candidates"],
        "output_keys": ["clustered_candidates", "candidate_lookup_to_cluster_id", "error"],
    },
    NODE_RESOLVE_NODES: {
        "description": (
            f"{LEGACY_KG_FILE_INGEST_NOTE} 本节点把聚类后的候选知识点解析成 knowledge_unit upsert，"
            "同时记录新增、更新和合并的节点 ID。新链路应优先看 kg_docs_sync 的稳定 anchor 与 source_ref。"
        ),
        "reads": ["clustered_candidates", "knowledge_unit", "embedding_cache"],
        "writes": ["knowledge_unit", "candidate_lookup_to_resolved_node_id", "new_node_ids", "updated_node_ids", "merged_node_ids"],
        "input_keys": ["subject", "clustered_candidates", "candidate_lookup_to_cluster_id"],
        "output_keys": [
            "candidate_lookup_to_resolved_node_id",
            "cluster_id_to_resolved_node_id",
            "new_node_ids",
            "updated_node_ids",
            "merged_node_ids",
            "error",
        ],
    },
    NODE_RESOLVE_EDGES: {
        "description": (
            f"{LEGACY_KG_FILE_INGEST_NOTE} 本节点把候选关系映射到已解析 knowledge_unit，执行 knowledge_edge upsert，"
            "并过滤无法定位端点或置信度不足的旧候选边。"
        ),
        "reads": ["all_candidate_edges", "candidate_lookup_to_resolved_node_id", "knowledge_edge"],
        "writes": ["knowledge_edge", "new_edge_ids", "updated_edge_ids"],
        "input_keys": ["subject", "all_candidate_edges", "candidate_lookup_to_resolved_node_id"],
        "output_keys": ["new_edge_ids", "updated_edge_ids", "error"],
    },
    NODE_ANALYZE_IMPACT: {
        "description": (
            f"{LEGACY_KG_FILE_INGEST_NOTE} 本节点基于本轮新增/更新/合并节点和边分析旧图谱影响面，"
            "供旧 job 结果页展示影响范围。正式文档同步链路不依赖这个节点。"
        ),
        "reads": ["new_node_ids", "updated_node_ids", "merged_node_ids", "new_edge_ids", "updated_edge_ids"],
        "writes": ["impact_set", "topic_anchor_snapshot"],
        "input_keys": ["subject", "new_node_ids", "updated_node_ids", "merged_node_ids", "new_edge_ids", "updated_edge_ids"],
        "output_keys": ["impact_set", "topic_anchor_snapshot", "error"],
    },
    NODE_FINALIZE_GRAPH: {
        "description": (
            f"{LEGACY_KG_FILE_INGEST_NOTE} 本节点收口旧构建 job，写入最终进度、摘要和影响面统计。"
            "如果没有 chunk 或构建被跳过，也会在这里结束旧 workflow。"
        ),
        "reads": ["job_id", "impact_set", "new_node_ids", "updated_node_ids", "new_edge_ids", "updated_edge_ids"],
        "writes": ["knowledge_build_job.status"],
        "input_keys": ["subject", "job_id", "impact_set", "error"],
        "output_keys": ["error"],
    },
    NODE_FAIL: {
        "description": (
            f"{LEGACY_KG_FILE_INGEST_NOTE} 本节点清理旧 pending job 并记录失败原因。出现这个节点时应优先确认是否还有上层误调旧入口。"
        ),
        "reads": ["job_id", "error"],
        "writes": ["knowledge_build_job.status", "pending_candidate_cleanup"],
        "input_keys": ["subject", "job_id", "error"],
        "output_keys": ["error"],
    },
}


def _trace_legacy_kg_node(trace, node_key: str, handler, *, timing_field: str | None = None):
    details = NODE_TRACE_DETAILS[node_key]
    return trace.node(
        handler,
        name=NODE_DISPLAY_NAMES[node_key],
        description=str(details["description"]),
        timing_field=timing_field,
        input_keys=list(details.get("input_keys") or []),
        output_keys=list(details.get("output_keys") or []),
        metadata=_langgraph_node_metadata(node_key),
    )


def _langgraph_node_metadata(node_key: str) -> dict[str, object]:
    details = NODE_TRACE_DETAILS[node_key]
    metadata: dict[str, object] = {
        "node_key": node_key,
        "node_display_name": NODE_DISPLAY_NAMES[node_key],
        "node_description": str(details["description"]),
        "reads": list(details.get("reads") or []),
        "writes": list(details.get("writes") or []),
        "state_inputs": list(details.get("input_keys") or []),
        "state_outputs": list(details.get("output_keys") or []),
        "deprecated": True,
        "replacement_workflow": "digest.kg_docs_sync",
    }
    if details.get("fanout"):
        metadata["fanout"] = str(details["fanout"])
    return metadata


def build_kg_digest_graph(*, context: WorkflowContext) -> StateGraph:
    """Build the LangGraph workflow for digest graph construction."""

    workflow = StateGraph(KGDigestState)
    trace = workflow_tracer(context=context, lane="kg_file_ingest")
    workflow.add_node(
        NODE_ACQUIRE_LOCK,
        _trace_legacy_kg_node(
            trace,
            NODE_ACQUIRE_LOCK,
            acquire_lock_node,
            timing_field="acquire_lock_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_ACQUIRE_LOCK),
    )
    workflow.add_node(
        NODE_PREPARE,
        _trace_legacy_kg_node(
            trace,
            NODE_PREPARE,
            prepare_node,
            timing_field="prepare_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_PREPARE),
    )
    workflow.add_node(
        NODE_EXTRACT,
        _trace_legacy_kg_node(
            trace,
            NODE_EXTRACT,
            extract_node,
            timing_field="extract_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_EXTRACT),
    )
    workflow.add_node(
        NODE_CLUSTER,
        _trace_legacy_kg_node(
            trace,
            NODE_CLUSTER,
            cluster_node,
            timing_field="cluster_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_CLUSTER),
    )
    workflow.add_node(
        NODE_RESOLVE_NODES,
        _trace_legacy_kg_node(
            trace,
            NODE_RESOLVE_NODES,
            resolve_nodes_node,
            timing_field="resolve_nodes_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_RESOLVE_NODES),
    )
    workflow.add_node(
        NODE_RESOLVE_EDGES,
        _trace_legacy_kg_node(
            trace,
            NODE_RESOLVE_EDGES,
            resolve_edges_node,
            timing_field="resolve_edges_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_RESOLVE_EDGES),
    )
    workflow.add_node(
        NODE_ANALYZE_IMPACT,
        _trace_legacy_kg_node(
            trace,
            NODE_ANALYZE_IMPACT,
            analyze_impact_node,
            timing_field="impact_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_ANALYZE_IMPACT),
    )
    workflow.add_node(
        NODE_FINALIZE_GRAPH,
        _trace_legacy_kg_node(
            trace,
            NODE_FINALIZE_GRAPH,
            build_finalize_graph_node(),
            timing_field="finalize_ms",
        ),
        metadata=_langgraph_node_metadata(NODE_FINALIZE_GRAPH),
    )
    workflow.add_node(
        NODE_FAIL,
        _trace_legacy_kg_node(
            trace,
            NODE_FAIL,
            fail_node,
        ),
        metadata=_langgraph_node_metadata(NODE_FAIL),
    )

    workflow.set_entry_point(NODE_ACQUIRE_LOCK)
    workflow.add_conditional_edges(
        NODE_ACQUIRE_LOCK,
        route_after_lock_for_trace,
        {
            "prepare": NODE_PREPARE,
            "fail": NODE_FAIL,
        },
    )
    workflow.add_conditional_edges(
        NODE_PREPARE,
        route_after_prepare_for_trace,
        {
            "extract": NODE_EXTRACT,
            "finalize_graph": NODE_FINALIZE_GRAPH,
            "fail": NODE_FAIL,
        },
    )
    workflow.add_conditional_edges(
        NODE_EXTRACT,
        route_after_step_for_trace,
        {
            "continue": NODE_CLUSTER,
            "fail": NODE_FAIL,
        },
    )
    workflow.add_conditional_edges(
        NODE_CLUSTER,
        route_after_step_for_trace,
        {
            "continue": NODE_RESOLVE_NODES,
            "fail": NODE_FAIL,
        },
    )
    workflow.add_conditional_edges(
        NODE_RESOLVE_NODES,
        route_after_step_for_trace,
        {
            "continue": NODE_RESOLVE_EDGES,
            "fail": NODE_FAIL,
        },
    )
    workflow.add_conditional_edges(
        NODE_RESOLVE_EDGES,
        route_after_step_for_trace,
        {
            "continue": NODE_ANALYZE_IMPACT,
            "fail": NODE_FAIL,
        },
    )
    workflow.add_conditional_edges(
        NODE_ANALYZE_IMPACT,
        route_after_step_for_trace,
        {
            "continue": NODE_FINALIZE_GRAPH,
            "fail": NODE_FAIL,
        },
    )
    workflow.add_edge(NODE_FINALIZE_GRAPH, END)
    workflow.add_edge(NODE_FAIL, END)
    return workflow


def create_graph_digest_initial_state(
    *,
    subject: str,
    file_ids: list[int],
    job_id: int,
    build_session_id: str | None = None,
    user_prompt: str | None = None,
    doc_chapter_metadatas: list[dict[str, object]] | None = None,
    subject_context: str | None = None,
) -> KnowledgeDigestState:
    """Create the initial state for digest graph building."""

    return {
        "subject": subject,
        "file_ids": file_ids,
        "job_id": job_id,
        "build_session_id": build_session_id or "",
        "user_prompt": user_prompt,
        "subject_context": subject_context or "",
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
