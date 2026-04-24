"""Interact chat graph definition and runtime entrypoints.

This file owns the LangGraph structure plus the single-run / SSE workflow
entrypoints for the interact chat lane. Session CRUD and HTTP-facing
use cases stay in ``use_cases.py``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from fastapi import Request
from langgraph.graph import END, StateGraph
from sqlmodel import Session

from app.shared.infra.workflow import workflow_tracer
from app.shared.infra.workflow.context import WorkflowContext, create_langgraph_dev_context
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow.graph_export import WorkflowGraphExport
from app.shared.infra.workflow.result import WorkflowResult, err_result
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.interact.chat.lib.events import (
    InteractCompletedEvent,
    InteractFailedEvent,
    InteractRequestedEvent,
)
from app.workflows.interact.chat.lib.streaming import SSEEventEmitter
from app.workflows.interact.chat.nodes import (
    build_load_history_state_node,
    build_persist_turn_node,
    build_prompt_node,
    build_retrieve_context_node,
    build_select_execution_mode_node,
    build_select_teaching_strategy_node,
    build_stream_answer_node,
)
from app.workflows.interact.chat.prompts.prompts import PROMPTS
from app.workflows.interact.chat.state import InteractWorkflowState


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


def create_interact_initial_state(
    *,
    subject: str,
    user_id: str,
    session_id: str | None,
    question: str,
    source: str | None = None,
    anchor_id: str | None = None,
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
) -> InteractWorkflowState:
    """Create the initial state for one interact workflow run."""

    return {
        "subject": subject,
        "user_id": user_id,
        "session_id": session_id,
        "question": question,
        "source": source,
        "anchor_id": anchor_id,
        "selected_context": selected_context,
        "source_chunk_id": source_chunk_id,
        "stream_interrupted": False,
        "error": None,
    }


async def run_interact_workflow(
    *,
    subject: str,
    user_id: str,
    session_id: str | None,
    question: str,
    session: Session,
    request: Request,
    emitter: SSEEventEmitter,
    source: str | None = None,
    anchor_id: str | None = None,
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
    event_bus: InProcessEventBus | None = None,
) -> WorkflowResult[InteractWorkflowState]:
    """Run the interact workflow once."""

    bus = event_bus or InProcessEventBus()
    await bus.publish(InteractRequestedEvent(subject=subject))
    context = WorkflowContext(
        workflow_name="interact.chat",
        subject=subject,
        event_bus=bus,
    )
    result = await run_state_graph(
        workflow_name="interact.chat",
        graph_builder=lambda: build_interact_workflow_graph(
            context=context,
            session=session,
            request=request,
            emitter=emitter,
        ),
        initial_state=create_interact_initial_state(
            subject=subject,
            user_id=user_id,
            session_id=session_id,
            question=question,
            source=source,
            anchor_id=anchor_id,
            selected_context=selected_context,
            source_chunk_id=source_chunk_id,
        ),
        context=context,
    )
    if result.failed:
        await bus.publish(
            InteractFailedEvent(
                subject=subject,
                error_message=result.error.detail,
            )
        )
        return result

    final_state = result.require_value()
    error_message = final_state.get("error")
    if error_message:
        await bus.publish(
            InteractFailedEvent(
                subject=subject,
                error_message=error_message,
            )
        )
        return err_result(
            "interact_workflow_failed",
            error_message,
            metadata={"subject": subject},
        )

    if not final_state.get("stream_interrupted"):
        await bus.publish(InteractCompletedEvent(subject=subject))
    return result


async def stream_chat_workflow(
    *,
    request: Request,
    session: Session,
    subject: str,
    user_id: str,
    session_id: str | None,
    question: str,
    source: str | None = None,
    anchor_id: str | None = None,
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
    event_bus: InProcessEventBus | None = None,
) -> AsyncGenerator[str, None]:
    """Stream one interact workflow run as SSE."""

    emitter = SSEEventEmitter()
    workflow_task = asyncio.create_task(
        _execute_interact_workflow(
            emitter=emitter,
            event_bus=event_bus,
            question=question,
            request=request,
            session_id=session_id,
            source=source,
            anchor_id=anchor_id,
            selected_context=selected_context,
            session=session,
            source_chunk_id=source_chunk_id,
            subject=subject,
            user_id=user_id,
        )
    )
    async for payload in emitter.stream(request=request, workflow_task=workflow_task):
        yield payload


async def _execute_interact_workflow(
    *,
    emitter: SSEEventEmitter,
    event_bus: InProcessEventBus | None,
    question: str,
    request: Request,
    session_id: str | None,
    source: str | None,
    anchor_id: str | None,
    selected_context: str | None,
    session: Session,
    source_chunk_id: int | None,
    subject: str,
    user_id: str,
) -> None:
    try:
        result = await run_interact_workflow(
            subject=subject,
            user_id=user_id,
            session_id=session_id,
            question=question,
            session=session,
            request=request,
            emitter=emitter,
            source=source,
            anchor_id=anchor_id,
            selected_context=selected_context,
            source_chunk_id=source_chunk_id,
            event_bus=event_bus,
        )
        if result.failed:
            await emitter.emit_error(
                detail=result.error.detail,
                error_code=result.error.code,
            )
            return

        final_state = result.require_value()
        if final_state.get("stream_interrupted"):
            return

        await emitter.emit_done(
            turn_id=final_state["turn_id"],
            contexts=final_state.get("contexts"),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await emitter.emit_error(
            detail=str(exc),
            error_code="interact_runtime_failed",
        )
    finally:
        await emitter.close()


WORKFLOW_EXPORTS = (
    WorkflowGraphExport(
        key="interact_flow",
        title="Interact Workflow",
        description="Teaching chat workflow with history loading, retrieval, strategy selection, primary-model SSE streaming, tool planning, and persistence.",
        build_graph=get_langgraph_dev_interact_graph,
        prompts=PROMPTS,
    ),
)


__all__ = [
    "InteractWorkflowState",
    "WORKFLOW_EXPORTS",
    "build_interact_workflow_graph",
    "create_interact_initial_state",
    "get_langgraph_dev_interact_graph",
    "run_interact_workflow",
    "stream_chat_workflow",
]
