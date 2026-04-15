"""Runtime entrypoints for the interact workflow."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from fastapi import Request
from sqlmodel import Session

from app.shared.infra.workflow.context import WorkflowContext
from app.shared.infra.workflow.events import InProcessEventBus
from app.shared.infra.workflow.result import WorkflowResult, err_result
from app.shared.infra.workflow.runtime import run_state_graph
from app.workflows.interact.events import (
    InteractCompletedEvent,
    InteractFailedEvent,
    InteractRequestedEvent,
)
from app.workflows.interact.graph import build_interact_workflow_graph
from app.workflows.interact.state import InteractWorkflowState
from app.workflows.interact.support.streaming import SSEEventEmitter


def create_interact_initial_state(
    *,
    subject: str,
    user_id: str,
    session_id: str | None,
    question: str,
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
) -> InteractWorkflowState:
    """Create the initial state for one interact workflow run."""

    return {
        "subject": subject,
        "user_id": user_id,
        "session_id": session_id,
        "question": question,
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


__all__ = [
    "create_interact_initial_state",
    "run_interact_workflow",
    "stream_chat_workflow",
]


