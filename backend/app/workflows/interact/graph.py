"""LangGraph definition for the interact workflow."""

from __future__ import annotations

from fastapi import Request
from langgraph.graph import END, StateGraph
from sqlmodel import Session

from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow import workflow_tracer
from app.workflows.interact.nodes import (
    build_select_execution_mode_node,
    build_load_history_state_node,
    build_persist_turn_node,
    build_prompt_node,
    build_retrieve_context_node,
    build_select_teaching_strategy_node,
    build_stream_answer_node,
)
from app.workflows.interact.state import InteractWorkflowState
from app.workflows.interact.support.streaming import SSEEventEmitter


def build_interact_workflow_graph(
    *,
    context: WorkflowContext | None = None,
    session: Session | None = None,
    request: Request | None = None,
    emitter: SSEEventEmitter | None = None,
) -> StateGraph:
    """Build the interact workflow graph."""

    workflow_name = context.workflow_name if context is not None else "interact.chat"
    workflow = StateGraph(InteractWorkflowState)
    trace = workflow_tracer(workflow=workflow_name, lane="chat")
    workflow.add_node(
        "load_history_state",
        trace.node(
            _resolve_history_node(context=context, session=session),
            name="load_history_state",
        ),
    )
    workflow.add_node(
        "retrieve_context",
        trace.node(
            _resolve_retrieval_node(context=context, session=session),
            name="retrieve_context",
        ),
    )
    workflow.add_node(
        "select_teaching_strategy",
        trace.node(
            _resolve_strategy_node(context=context),
            name="select_teaching_strategy",
        ),
    )
    workflow.add_node(
        "select_execution_mode",
        trace.node(
            _resolve_execution_mode_node(context=context),
            name="select_execution_mode",
        ),
    )
    workflow.add_node(
        "build_prompt",
        trace.node(
            _resolve_prompt_node(context=context),
            name="build_prompt",
        ),
    )
    workflow.add_node(
        "stream_answer",
        trace.node(
            _resolve_stream_node(
                context=context,
                request=request,
                emitter=emitter,
            ),
            name="stream_answer",
        ),
    )
    workflow.add_node(
        "persist_turn",
        trace.node(
            _resolve_persist_node(context=context, session=session),
            name="persist_turn",
        ),
    )

    workflow.set_entry_point("load_history_state")
    workflow.add_conditional_edges(
        "load_history_state",
        _route_after_standard_step,
        {
            "continue": "retrieve_context",
            "finish": END,
        },
    )
    workflow.add_conditional_edges(
        "retrieve_context",
        _route_after_standard_step,
        {
            "continue": "select_teaching_strategy",
            "finish": END,
        },
    )
    workflow.add_conditional_edges(
        "select_teaching_strategy",
        _route_after_standard_step,
        {
            "continue": "select_execution_mode",
            "finish": END,
        },
    )
    workflow.add_conditional_edges(
        "select_execution_mode",
        _route_after_standard_step,
        {
            "continue": "build_prompt",
            "finish": END,
        },
    )
    workflow.add_conditional_edges(
        "build_prompt",
        _route_after_standard_step,
        {
            "continue": "stream_answer",
            "finish": END,
        },
    )
    workflow.add_conditional_edges(
        "stream_answer",
        _route_after_stream_step,
        {
            "continue": "persist_turn",
            "finish": END,
        },
    )
    workflow.add_edge("persist_turn", END)
    return workflow

def _route_after_standard_step(state: InteractWorkflowState) -> str:
    return "finish" if state.get("error") else "continue"


def _route_after_stream_step(state: InteractWorkflowState) -> str:
    if state.get("error") or state.get("stream_interrupted"):
        return "finish"
    return "continue"


def _resolve_history_node(
    *,
    context: WorkflowContext | None,
    session: Session | None,
):
    if context is None:
        return _noop_node
    return build_load_history_state_node(context=context, session=session)


def _resolve_retrieval_node(
    *,
    context: WorkflowContext | None,
    session: Session | None,
):
    if context is None:
        return _noop_node
    return build_retrieve_context_node(context=context, session=session)


def _resolve_strategy_node(*, context: WorkflowContext | None):
    if context is None:
        return _noop_node
    return build_select_teaching_strategy_node(context=context)


def _resolve_execution_mode_node(*, context: WorkflowContext | None):
    if context is None:
        return _noop_node
    return build_select_execution_mode_node(context=context)


def _resolve_prompt_node(*, context: WorkflowContext | None):
    if context is None:
        return _noop_node
    return build_prompt_node(context=context)


def _resolve_stream_node(
    *,
    context: WorkflowContext | None,
    request: Request | None,
    emitter: SSEEventEmitter | None,
):
    if context is None:
        return _noop_node
    return build_stream_answer_node(context=context, request=request, emitter=emitter)


def _resolve_persist_node(
    *,
    context: WorkflowContext | None,
    session: Session | None,
):
    if context is None:
        return _noop_node
    return build_persist_turn_node(context=context, session=session)


def _noop_node(state: InteractWorkflowState) -> InteractWorkflowState:
    return state


def get_langgraph_dev_interact_graph() -> StateGraph:
    """Create the interact graph used by ``langgraph dev``."""

    return build_interact_workflow_graph(
        context=create_langgraph_dev_context("interact.chat.langgraph_dev"),
    )


__all__ = [
    "InteractWorkflowState",
    "build_interact_workflow_graph",
    "get_langgraph_dev_interact_graph",
]


