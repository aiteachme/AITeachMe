"""Streaming node builders for the interact workflow.

Reads DB: none.
Writes DB: none directly; persistence happens in the next node.
Writes FS: none.
Idempotency: non-idempotent external LLM stream; on rerun it generates a fresh assistant response.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Request

from app.shared.infra.agent_loop import run_agent_loop_stream
from app.shared.infra.llm_support import acompletion_stream
from app.shared.infra.llm_support.model_choices import normalize_runtime_model_override
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.interact.chat.state import InteractWorkflowState
from app.workflows.interact.chat.lib.execution import InteractExecutionMode
from app.workflows.interact.chat.lib.home_intake import (
    run_home_intake_turn,
    should_use_home_intake_flow,
)
from app.workflows.interact.chat.lib.streaming import SSEEventEmitter
from app.workflows.interact.chat.lib.tooling import (
    INTERACT_MODEL_SELECTOR,
    build_agent_loop_config,
    build_interact_provider_native_tools,
    resolve_interact_tool_plan,
    synthesize_ask_user_options_action,
)
from app.workflows.interact.chat.lib.model_policy import (
    InteractModelStep,
    get_interact_model_policy,
    interact_completion_kwargs_with_metadata,
)


_TOOL_DISPLAY_NAMES = {
    "ask_user_options": "\u8be2\u95ee\u7528\u6237",
    "web_search": "联网搜索",
    "recall_info": "回忆用户信息",
    "remember_info": "记住用户信息",
    "search_kb": "检索课程知识库",
    "read_course_document": "查看知识文档",
    "read_course_profile": "查看课程画像",
    "read_course_exams": "查看测验记录",
    "create_course_from_home_intake": "创建学科",
}


async def _is_disconnected(request: Request | None) -> bool:
    if request is None:
        return False
    return await request.is_disconnected()


async def _emit_token(emitter: SSEEventEmitter | None, token: str) -> None:
    if emitter is None:
        return
    await emitter.emit_token(token)


def _split_progressive_tokens(text: str) -> list[str]:
    if len(text) <= 36:
        return [text]

    chunks: list[str] = []
    buffer: list[str] = []
    for char in text:
        buffer.append(char)
        if char in "。！？!?；;\n" or len(buffer) >= 24:
            chunks.append("".join(buffer))
            buffer = []
    if buffer:
        chunks.append("".join(buffer))
    return [chunk for chunk in chunks if chunk]


async def _collect_and_emit_text(
    emitter: SSEEventEmitter | None,
    collected_tokens: list[str],
    text: str,
) -> None:
    if emitter is None:
        collected_tokens.append(text)
        return
    chunks = _split_progressive_tokens(text)
    for chunk in chunks:
        collected_tokens.append(chunk)
        await _emit_token(emitter, chunk)
        if len(chunks) > 1:
            await asyncio.sleep(0)


async def _emit_status(
    emitter: SSEEventEmitter | None,
    stage: str,
    detail: str,
    **extra: object,
) -> None:
    if emitter is None:
        return
    await emitter.emit_status(stage=stage, detail=detail, **extra)


def _build_tool_event_handler(
    emitter: SSEEventEmitter | None,
) -> Callable[[dict[str, Any]], Awaitable[None]] | None:
    if emitter is None:
        return None

    async def handle_tool_event(event: dict[str, Any]) -> None:
        phase = str(event.get("phase") or "").strip()
        tool_name = str(event.get("tool_name") or "").strip()
        if not phase or not tool_name:
            return
        display_name = _TOOL_DISPLAY_NAMES.get(tool_name, tool_name)
        stage = {
            "started": "tool_call_started",
            "completed": "tool_call_completed",
            "failed": "tool_call_failed",
        }.get(phase)
        if stage is None:
            return
        detail = _tool_status_detail(phase, display_name)
        await _emit_status(
            emitter,
            stage,
            detail,
            tool_name=tool_name,
            tool_display_name=display_name,
            tool_phase=phase,
            tool_call_id=str(event.get("tool_call_id") or ""),
            elapsed_s=event.get("elapsed_s"),
            success=event.get("success"),
            argument_names=event.get("argument_names") if phase == "started" else None,
        )

    return handle_tool_event


def _tool_status_detail(phase: str, display_name: str) -> str:
    if phase == "started":
        return f"正在{display_name}"
    if phase == "completed":
        return f"已完成{display_name}"
    if phase == "failed":
        return f"{display_name}失败"
    return f"{display_name}状态更新"


def _answering_status_detail(tool_names: list[str]) -> str:
    if not tool_names:
        return "正在组织回答..."
    if "web_search" in tool_names:
        return "正在判断是否需要联网检索..."
    if any(
        name in tool_names
        for name in ("read_course_document", "read_course_profile", "read_course_exams")
    ):
        return "正在判断是否需要查看课程上下文..."
    if "search_kb" in tool_names:
        return "正在检索课程资料..."
    return "正在准备可用工具..."


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


def _build_response_stream(
    state: InteractWorkflowState,
    *,
    course_id: str,
    model_selector: str,
    emitter: SSEEventEmitter | None = None,
    client_action_handler: Callable[[list[dict[str, Any]], dict[str, Any]], Awaitable[None] | None] | None = None,
):
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
        scene=state.get("scene"),
        source=state.get("source"),
        question=state.get("question"),
    )
    provider_native_tools = build_interact_provider_native_tools(
        tool_plan=tool_plan,
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
                user_id=state.get("user_id"),
                session_id=state.get("session_id"),
                source=state.get("source"),
                provider_native_tools=provider_native_tools,
                model_selector=model_selector,
                tool_event_handler=_build_tool_event_handler(emitter),
                client_action_handler=client_action_handler,
                extra_metadata=trace_metadata,
            ),
        )
    return acompletion_stream(
        state["messages"],
        **interact_completion_kwargs_with_metadata(
            InteractModelStep.RESPONSE_STREAM,
            model_override=model_override,
            extra_metadata=trace_metadata,
            provider_native_tools=bool(provider_native_tools),
        ),
        provider_native_tools=provider_native_tools or None,
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
        if should_use_home_intake_flow(
            scene=state.get("scene"),
            source=state.get("source"),
            course_id=course_id,
            question=state.get("question"),
            recent_messages=state.get("recent_messages", []),
        ):
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
                    tool_event_handler=_build_tool_event_handler(emitter),
                )
                if await _is_disconnected(request):
                    workflow_logger.info("home_intake_stream_disconnected")
                    return _build_stream_state(
                        state,
                        collected_tokens,
                        stream_interrupted=True,
                    )
                if result.assistant_response:
                    await _emit_status(emitter, "home_intake", "正在生成回复...")
                    await _collect_and_emit_text(
                        emitter,
                        collected_tokens,
                        result.assistant_response,
                    )
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

        model_selector = INTERACT_MODEL_SELECTOR
        execution_mode = state.get("execution_mode", InteractExecutionMode.SINGLE_PASS)
        tool_plan = resolve_interact_tool_plan(
            execution_mode=execution_mode,
            course_id=course_id,
            retrieval_results=state.get("retrieval_results", []),
            scene=state.get("scene"),
            source=state.get("source"),
            question=state.get("question"),
        )
        provider_native_tools = build_interact_provider_native_tools(
            tool_plan=tool_plan,
            course_id=course_id,
            retrieval_results=state.get("retrieval_results", []),
        )
        await _emit_status(
            emitter,
            "answering",
            _answering_status_detail(tool_plan.tool_names),
            execution_mode=execution_mode.value,
            tools=tool_plan.tool_names,
            provider_native_tools=[tool.get("type") for tool in provider_native_tools],
            model=model_selector,
            model_override=normalize_runtime_model_override(state.get("model_override")),
        )
        agent_client_actions: list[dict[str, Any]] = []

        async def collect_client_actions(
            actions: list[dict[str, Any]],
            _metadata: dict[str, Any],
        ) -> None:
            agent_client_actions.extend(actions)

        stream = _build_response_stream(
            state,
            course_id=course_id,
            model_selector=model_selector,
            emitter=emitter,
            client_action_handler=collect_client_actions,
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
        client_actions = synthesize_ask_user_options_action(
            question=state.get("question"),
            assistant_response=assistant_response,
            existing_client_actions=agent_client_actions or None,
        )
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
            client_actions=client_actions or None,
        )

    return stream_answer
