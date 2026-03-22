"""Streaming node builders for the interact workflow."""

from __future__ import annotations

from fastapi import Request

from app.core.llm import acompletion_stream
from app.core.model_router import TaskType
from app.workflows.common.context import WorkflowContext
from app.workflows.interact.state import InteractWorkflowState
from app.workflows.interact.support.streaming import SSEEventEmitter


def build_stream_answer_node(
    *,
    context: WorkflowContext,
    request: Request,
    emitter: SSEEventEmitter,
):
    """Build the node that streams assistant tokens to the client."""

    workflow_logger = context.get_logger()

    async def stream_answer(state: InteractWorkflowState) -> InteractWorkflowState:
        if state.get("error"):
            return state

        collected_tokens: list[str] = []
        stream = acompletion_stream(
            state["messages"],
            task_type=TaskType.CHAT,
        )
        try:
            async for token in stream:
                if await request.is_disconnected():
                    await stream.aclose()
                    workflow_logger.info("interact_stream_disconnected")
                    return {
                        **state,
                        "assistant_response": "".join(collected_tokens),
                        "stream_interrupted": True,
                    }
                collected_tokens.append(token)
                await emitter.emit_token(token)
        except Exception as exc:
            workflow_logger.exception("interact_stream_failed")
            return {
                **state,
                "assistant_response": "".join(collected_tokens),
                "error": str(exc),
            }

        assistant_response = "".join(collected_tokens)
        workflow_logger.info(
            "interact_stream_completed",
            response_chars=len(assistant_response),
        )
        return {
            **state,
            "assistant_response": assistant_response,
            "stream_interrupted": False,
        }

    return stream_answer
