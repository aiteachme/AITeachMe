"""Streaming node builders for the interact workflow.

Reads DB: none.
Writes DB: none directly; persistence happens in the next node.
Writes FS: none.
Idempotency: non-idempotent external LLM stream; on rerun it generates a fresh assistant response.
"""

from __future__ import annotations

from fastapi import Request

from app.shared.infra.llm_support import acompletion_stream
from app.shared.infra.llm_support.routing import TaskType
from app.shared.infra.tracing import llm_trace_scope
from app.workflows.common.context import WorkflowContext
from app.workflows.interact.state import InteractWorkflowState
from app.workflows.interact.support.streaming import SSEEventEmitter


async def _is_disconnected(request: Request | None) -> bool:
    if request is None:
        return False
    return await request.is_disconnected()


async def _emit_token(emitter: SSEEventEmitter | None, token: str) -> None:
    if emitter is None:
        return
    await emitter.emit_token(token)


def _build_stream_state(
    state: InteractWorkflowState,
    collected_tokens: list[str],
    *,
    stream_interrupted: bool | None = None,
    error: str | None = None,
) -> InteractWorkflowState:
    next_state: InteractWorkflowState = {
        **state,
        "assistant_response": "".join(collected_tokens),
    }
    if stream_interrupted is not None:
        next_state["stream_interrupted"] = stream_interrupted
    if error is not None:
        next_state["error"] = error
    return next_state


def build_stream_answer_node(
    *,
    context: WorkflowContext,
    request: Request | None = None,
    emitter: SSEEventEmitter | None = None,
):
    """Build the node that streams assistant tokens to the client."""

    workflow_logger = context.get_logger()

    async def stream_answer(state: InteractWorkflowState) -> InteractWorkflowState:
        if state.get("error"):
            return state

        collected_tokens: list[str] = []
        subject = str(state.get("subject") or context.subject or "")
        build_session_id = str(state.get("session_id") or "")
        with llm_trace_scope(
            subject=subject,
            build_session_id=build_session_id,
            workflow=context.workflow_name,
            lane="chat",
            node="stream_answer",
        ):
            stream = acompletion_stream(
                state["messages"],
                task_type=TaskType.CHAT,
            )
            try:
                async for token in stream:
                    if await _is_disconnected(request):
                        await stream.aclose()
                        workflow_logger.info("interact_stream_disconnected")
                        return _build_stream_state(
                            state,
                            collected_tokens,
                            stream_interrupted=True,
                        )
                    collected_tokens.append(token)
                    await _emit_token(emitter, token)
            except Exception as exc:
                workflow_logger.exception("interact_stream_failed")
                return _build_stream_state(
                    state,
                    collected_tokens,
                    error=str(exc),
                )

        assistant_response = "".join(collected_tokens)
        workflow_logger.info(
            "interact_stream_completed",
            response_chars=len(assistant_response),
            streaming_enabled=emitter is not None,
        )
        return _build_stream_state(
            state,
            collected_tokens,
            stream_interrupted=False,
        )

    return stream_answer
