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


def build_docs_sync_graph(*, context: WorkflowContext) -> StateGraph:
    workflow = StateGraph(DocsSyncState)
    trace = workflow_tracer(context=context, lane="kg_docs_sync")
    workflow.add_node("prepare", trace.node(prepare_node, name="校验同步输入"))
    workflow.add_node("sync", trace.node(run_docs_sync_node, name="同步知识单元与关系"))
    workflow.add_node("finalize", trace.node(finalize_node, name="收口同步结果"))
    workflow.add_node("fail", trace.node(fail_node, name="记录同步失败"))

    workflow.set_entry_point("prepare")
    workflow.add_conditional_edges(
        "prepare",
        route_after_prepare_for_trace,
        {"sync": "sync", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "sync",
        route_after_sync_for_trace,
        {"finalize": "finalize", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "finalize",
        route_after_finalize_for_trace,
        {"end": END, "fail": "fail"},
    )
    workflow.add_edge("fail", END)
    return workflow


def create_docs_sync_initial_state(
    *,
    subject: str,
    markdown: str,
    build_revision_no: int | None,
    build_session_id: str | None = None,
    subject_context: str | None = None,
) -> DocsSyncState:
    return {
        "subject": subject,
        "markdown": markdown,
        "subject_context": subject_context or "",
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
