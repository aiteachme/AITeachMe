"""Streaming node builders for the interact workflow.

Reads DB: none.
Writes DB: none directly; persistence happens in the next node.
Writes FS: none.
Idempotency: non-idempotent external LLM stream; on rerun it generates a fresh assistant response.
"""

from __future__ import annotations

from fastapi import Request

from app.shared.infra.agent_loop import run_agent_loop_stream
from app.shared.infra.llm_support import acompletion_stream
from app.shared.infra.llm_support.model_choices import normalize_runtime_model_override
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.interact.chat.state import InteractWorkflowState
from app.workflows.interact.chat.lib.execution import InteractExecutionMode
from app.workflows.interact.chat.lib.streaming import SSEEventEmitter
from app.workflows.interact.chat.lib.tooling import (
    INTERACT_MODEL_SELECTOR,
    build_agent_loop_config,
    resolve_interact_tool_plan,
)


async def _is_disconnected(request: Request | None) -> bool:
    if request is None:
        return False
    return await request.is_disconnected()


async def _emit_token(emitter: SSEEventEmitter | None, token: str) -> None:
    if emitter is None:
        return
    await emitter.emit_token(token)


async def _emit_status(
    emitter: SSEEventEmitter | None,
    stage: str,
    detail: str,
    **extra: object,
) -> None:
    if emitter is None:
        return
    await emitter.emit_status(stage=stage, detail=detail, **extra)


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


def _build_response_stream(state: InteractWorkflowState, *, course_id: str, model_selector: str):
    execution_mode = state.get("execution_mode", InteractExecutionMode.SINGLE_PASS)
    tool_plan = resolve_interact_tool_plan(
        execution_mode=execution_mode,
        course_id=course_id,
        retrieval_results=state.get("retrieval_results", []),
    )
    if tool_plan.uses_tools:
        return run_agent_loop_stream(
            state["messages"],
            tools=tool_plan.tool_names,
            config=build_agent_loop_config(
                tool_plan=tool_plan,
                course_id=course_id,
                model_selector=model_selector,
            ),
        )
    return acompletion_stream(
        state["messages"],
        call_purpose=LLMCallPurpose.CHAT,
        model=model_selector,
    )


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
        course_id = str(state.get("course_id") or context.course_id or "")
        model_selector = INTERACT_MODEL_SELECTOR
        execution_mode = state.get("execution_mode", InteractExecutionMode.SINGLE_PASS)
        tool_plan = resolve_interact_tool_plan(
            execution_mode=execution_mode,
            course_id=course_id,
            retrieval_results=state.get("retrieval_results", []),
        )
        await _emit_status(
            emitter,
            "answering",
            "正在组织回答..." if not tool_plan.uses_tools else "正在结合知识库工具整理回答...",
            execution_mode=execution_mode.value,
            tools=tool_plan.tool_names,
            model=model_selector,
            model_override=normalize_runtime_model_override(state.get("model_override")),
        )
        stream = _build_response_stream(state, course_id=course_id, model_selector=model_selector)
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
            execution_mode=state.get("execution_mode", InteractExecutionMode.SINGLE_PASS).value,
            model=model_selector,
            model_override=normalize_runtime_model_override(state.get("model_override")),
        )
        return _build_stream_state(
            state,
            collected_tokens,
            stream_interrupted=False,
        )

    return stream_answer
