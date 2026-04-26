"""Docs-sync workflow graph."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.workflows.digest.kg_docs_sync.nodes import (
    fail_node,
    finalize_node,
    prepare_node,
    run_docs_sync_node,
)
from app.workflows.digest.kg_docs_sync.state import DocsSyncState

RUN_NAME_KG_DOCS_SYNC = "知识图谱同步：根据知识文档更新图谱"

NODE_PREPARE = "prepare"
NODE_SYNC = "sync"
NODE_FINALIZE = "finalize"
NODE_FAIL = "fail"

NODE_DISPLAY_NAMES = {
    NODE_PREPARE: "校验同步输入",
    NODE_SYNC: "同步知识单元与关系",
    NODE_FINALIZE: "收口同步结果",
    NODE_FAIL: "记录同步失败",
}

NODE_TRACE_DETAILS: dict[str, dict[str, object]] = {
    NODE_PREPARE: {
        "description": (
            "校验 kg_docs_sync 的正式输入：必须有学科名和最新知识文档 Markdown，并保留 structured_context。"
            "structured_context 里会带 docgen_manifest、document_backbone、章节来源映射和文档版本等结构化信号，"
            "这些内容后续用于稳定节点身份、来源追踪和图谱质量指标。"
        ),
        "reads": ["KnowledgeDoc markdown", "structured_context", "Subject.document_summary_json"],
        "writes": ["validated docs-sync state", "error"],
        "input_keys": ["subject", "markdown", "structured_context", "subject_context", "build_revision_no"],
        "output_keys": ["subject", "markdown", "structured_context", "error"],
    },
    NODE_SYNC: {
        "description": (
            "打开数据库会话并执行增量知识图谱同步：按章节抽取候选知识点和关系，合并 DocGen backbone 中的术语/依赖，"
            "做候选过滤、稳定 anchor 去重、节点/边 upsert、source_ref 写入和旧节点/旧边降级。"
            "该节点是 kg_docs_sync 的主工作区，LLM 子调用集中在复用抽取器内部，子 span 会挂在同一条 LangSmith 链路下。"
        ),
        "reads": [
            "knowledge_document",
            "knowledge_unit",
            "knowledge_edge",
            "knowledge_graph_sync_run",
            "knowledge_graph_source_ref",
            "docgen_manifest",
            "document_backbone",
        ],
        "writes": [
            "knowledge_unit",
            "knowledge_edge",
            "knowledge_graph_sync_run",
            "knowledge_graph_source_ref",
            "KnowledgeSyncReport",
        ],
        "input_keys": ["subject", "markdown", "subject_context", "structured_context", "build_revision_no", "build_session_id"],
        "output_keys": ["report", "error"],
    },
    NODE_FINALIZE: {
        "description": (
            "检查同步报告是否存在，并把成功状态交给上层 graph lane runtime。"
            "报告里包含 unit/edge 变更数、章节处理数、LLM/fallback 统计、source_ref 数量、backbone 命中数、稳定 anchor 数和废弃实体数。"
        ),
        "reads": ["KnowledgeSyncReport"],
        "writes": ["final docs-sync state", "error"],
        "input_keys": ["report", "error"],
        "output_keys": ["report", "error"],
    },
    NODE_FAIL: {
        "description": (
            "统一记录 kg_docs_sync 失败状态。上游可能来自输入缺失、增量同步异常、DB 写入异常或报告缺失；"
            "这里不再吞掉错误，只把 error 留在 state 中让 workflow result 和 graph runtime 显示失败。"
        ),
        "reads": ["error", "subject", "build_session_id"],
        "writes": ["error"],
        "input_keys": ["subject", "build_session_id", "error"],
        "output_keys": ["error"],
    },
}


def _named_route(fn, name: str):
    fn.__name__ = name
    fn.__qualname__ = name
    return fn


def route_after_prepare(state: DocsSyncState) -> str:
    return "sync" if not state.get("error") else "fail"


def route_after_sync(state: DocsSyncState) -> str:
    return "finalize" if not state.get("error") else "fail"


def route_after_finalize(state: DocsSyncState) -> str:
    return "end" if not state.get("error") else "fail"


route_after_prepare_for_trace = _named_route(route_after_prepare, "检查输入后继续同步")
route_after_sync_for_trace = _named_route(route_after_sync, "检查同步是否成功")
route_after_finalize_for_trace = _named_route(route_after_finalize, "检查是否完成")


def _trace_docs_sync_node(trace, node_key: str, handler):
    details = NODE_TRACE_DETAILS[node_key]
    return trace.node(
        handler,
        name=NODE_DISPLAY_NAMES[node_key],
        description=str(details["description"]),
        input_keys=list(details.get("input_keys") or []),
        output_keys=list(details.get("output_keys") or []),
        metadata=_langgraph_node_metadata(node_key),
    )


def _langgraph_node_metadata(node_key: str) -> dict[str, object]:
    details = NODE_TRACE_DETAILS[node_key]
    return {
        "node_key": node_key,
        "node_display_name": NODE_DISPLAY_NAMES[node_key],
        "node_description": str(details["description"]),
        "reads": list(details.get("reads") or []),
        "writes": list(details.get("writes") or []),
        "state_inputs": list(details.get("input_keys") or []),
        "state_outputs": list(details.get("output_keys") or []),
    }


def build_docs_sync_graph(*, context: WorkflowContext) -> StateGraph:
    workflow = StateGraph(DocsSyncState)
    trace = workflow_tracer(context=context, lane="kg_docs_sync")
    workflow.add_node(
        NODE_PREPARE,
        _trace_docs_sync_node(trace, NODE_PREPARE, prepare_node),
        metadata=_langgraph_node_metadata(NODE_PREPARE),
    )
    workflow.add_node(
        NODE_SYNC,
        _trace_docs_sync_node(trace, NODE_SYNC, run_docs_sync_node),
        metadata=_langgraph_node_metadata(NODE_SYNC),
    )
    workflow.add_node(
        NODE_FINALIZE,
        _trace_docs_sync_node(trace, NODE_FINALIZE, finalize_node),
        metadata=_langgraph_node_metadata(NODE_FINALIZE),
    )
    workflow.add_node(
        NODE_FAIL,
        _trace_docs_sync_node(trace, NODE_FAIL, fail_node),
        metadata=_langgraph_node_metadata(NODE_FAIL),
    )

    workflow.set_entry_point(NODE_PREPARE)
    workflow.add_conditional_edges(
        NODE_PREPARE,
        route_after_prepare_for_trace,
        {"sync": NODE_SYNC, "fail": NODE_FAIL},
    )
    workflow.add_conditional_edges(
        NODE_SYNC,
        route_after_sync_for_trace,
        {"finalize": NODE_FINALIZE, "fail": NODE_FAIL},
    )
    workflow.add_conditional_edges(
        NODE_FINALIZE,
        route_after_finalize_for_trace,
        {"end": END, "fail": NODE_FAIL},
    )
    workflow.add_edge(NODE_FAIL, END)
    return workflow


def create_docs_sync_initial_state(
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None,
    build_session_id: str | None = None,
    subject_context: str | None = None,
    structured_context: dict[str, object] | None = None,
) -> DocsSyncState:
    return {
        "subject": subject,
        "markdown": markdown,
        "subject_context": subject_context or "",
        "structured_context": dict(structured_context or {}),
        "build_revision_no": build_revision_no,
        "build_session_id": build_session_id or "",
        "report": None,
        "error": None,
    }


def get_langgraph_dev_kg_docs_sync_graph() -> StateGraph:
    return build_docs_sync_graph(context=create_langgraph_dev_context("digest.kg_docs_sync.langgraph_dev"))


__all__ = [
    "RUN_NAME_KG_DOCS_SYNC",
    "build_docs_sync_graph",
    "create_docs_sync_initial_state",
    "get_langgraph_dev_kg_docs_sync_graph",
]
