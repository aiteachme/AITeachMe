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
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.interact.chat.state import InteractWorkflowState
from app.workflows.interact.chat.lib.execution import InteractExecutionMode
from app.workflows.interact.chat.lib.home_intake import (
    is_home_intake_source,
    run_home_intake_turn,
)
from app.workflows.interact.chat.lib.streaming import SSEEventEmitter
from app.workflows.interact.chat.lib.tooling import (
    INTERACT_MODEL_SELECTOR,
    build_agent_loop_config,
    resolve_interact_tool_plan,
)
from app.workflows.interact.chat.lib.model_policy import (
    InteractModelStep,
    get_interact_model_policy,
    interact_completion_kwargs_with_metadata,
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
    client_actions: list[dict] | None = None,
) -> InteractWorkflowState:
    next_state: InteractWorkflowState = {
        **state,
        "assistant_response": "".join(collected_tokens),
    }
    if stream_interrupted is not None:
        next_state["stream_interrupted"] = stream_interrupted
    if error is not None:
        next_state["error"] = error
    if client_actions is not None:
        next_state["client_actions"] = client_actions
    return next_state


def _chat_model_trace_metadata(*, model_selector: str, model_override: str | None) -> dict[str, object]:
    metadata = get_interact_model_policy(InteractModelStep.RESPONSE_STREAM).metadata(
        model_override=model_override,
    )
    metadata["chat_model_slot"] = model_selector
    if not model_override:
        metadata["chat_model_override"] = "settings"
    return metadata


def _build_response_stream(state: InteractWorkflowState, *, course_id: str, model_selector: str):
    execution_mode = state.get("execution_mode", InteractExecutionMode.SINGLE_PASS)
    model_override = normalize_runtime_model_override(state.get("model_override"))
    trace_metadata = _chat_model_trace_metadata(
        model_selector=model_selector,
        model_override=model_override,
    )
    tool_plan = resolve_interact_tool_plan(
        execution_mode=execution_mode,
        course_id=course_id,
        retrieval_results=state.get("retrieval_results", []),
        source=state.get("source"),
    )
    if tool_plan.uses_tools:
        return run_agent_loop_stream(
            state["messages"],
            tools=tool_plan.tool_names,
            config=build_agent_loop_config(
                tool_plan=tool_plan,
                course_id=course_id,
                user_id=state.get("user_id"),
                session_id=state.get("session_id"),
                source=state.get("source"),
                model_selector=model_selector,
                extra_metadata=trace_metadata,
            ),
        )
    return acompletion_stream(
        state["messages"],
        **interact_completion_kwargs_with_metadata(
            InteractModelStep.RESPONSE_STREAM,
            model_override=model_override,
            extra_metadata=trace_metadata,
        ),
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
        if is_home_intake_source(state.get("source")):
            await _emit_status(
                emitter,
                "home_intake",
                "正在理解你的意图...",
                model=normalize_runtime_model_override(state.get("model_override")) or "settings",
            )
            try:
                background_task_registry = (
                    getattr(request.app.state, "background_task_registry", None)
                    if request is not None
                    else None
                )
                result = await run_home_intake_turn(
                    state,
                    background_task_registry=background_task_registry,
                )
                if await _is_disconnected(request):
                    workflow_logger.info("home_intake_stream_disconnected")
                    return _build_stream_state(
                        state,
                        collected_tokens,
                        stream_interrupted=True,
                    )
                if result.assistant_response:
                    collected_tokens.append(result.assistant_response)
                    await _emit_token(emitter, result.assistant_response)
                return _build_stream_state(
                    state,
                    collected_tokens,
                    stream_interrupted=False,
                    client_actions=result.client_actions,
                )
            except Exception as exc:
                workflow_logger.exception("home_intake_stream_failed")
                return _build_stream_state(
                    state,
                    collected_tokens,
                    error=str(exc),
                )

        course_id = str(state.get("course_id") or context.course_id or "")
        model_selector = INTERACT_MODEL_SELECTOR
        execution_mode = state.get("execution_mode", InteractExecutionMode.SINGLE_PASS)
        tool_plan = resolve_interact_tool_plan(
            execution_mode=execution_mode,
            course_id=course_id,
            retrieval_results=state.get("retrieval_results", []),
            source=state.get("source"),
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
