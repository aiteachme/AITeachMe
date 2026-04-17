"""Docs-sync workflow graph."""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.workflows.digest.kg_docs_sync.nodes import (
    fail_node,
    finalize_node,
    prepare_node,
    run_docs_sync_node,
)
from app.workflows.digest.kg_docs_sync.state import DocsSyncState


def build_docs_sync_graph() -> StateGraph:
    workflow = StateGraph(DocsSyncState)
    workflow.add_node("prepare", prepare_node)
    workflow.add_node("sync", run_docs_sync_node)
    workflow.add_node("finalize", finalize_node)
    workflow.add_node("fail", fail_node)

    workflow.set_entry_point("prepare")
    workflow.add_conditional_edges(
        "prepare",
        lambda state: "sync" if not state.get("error") else "fail",
        {"sync": "sync", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "sync",
        lambda state: "finalize" if not state.get("error") else "fail",
        {"finalize": "finalize", "fail": "fail"},
    )
    workflow.add_conditional_edges(
        "finalize",
        lambda state: "end" if not state.get("error") else "fail",
        {"end": END, "fail": "fail"},
    )
    workflow.add_edge("fail", END)
    return workflow


def run_docs_sync_graph(initial_state: DocsSyncState) -> DocsSyncState:
    graph = build_docs_sync_graph().compile()
    result = graph.invoke(initial_state)
    return dict(result)


__all__ = ["build_docs_sync_graph", "run_docs_sync_graph"]
