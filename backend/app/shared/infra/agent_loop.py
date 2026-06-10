"""Agent Loop — 工具增强的 LLM 推理循环。

实现 ReAct 模式：Reason → Act (tool call) → Observe → Repeat。

对外只需一行调用::

    from app.shared.infra.agent_loop import run_agent_loop
    result = await run_agent_loop(messages, tools=["search_kb"])
    answer = result.final_answer
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import structlog

from app.shared.infra.llm_support.native_tools import without_provider_native_tools
from app.shared.infra.llm_support.routing import TaskType

logger = structlog.get_logger()

# ── 配置 ──────────────────────────────────────────────────────


@dataclass
class AgentLoopConfig:
    """Agent Loop 配置。

    Attributes:
        max_iterations: 最大循环次数（安全阀，防止无限循环）。
        max_tool_calls_per_turn: 同一轮 LLM 响应中最多执行几个工具调用。
        tool_timeout_s: 单个工具执行超时（秒）。
        task_type: 任务类型，用于调用 profile 和观测标签。
        model: 模型选择器，默认固定使用 settings.models.primary。
        result_max_chars: 工具返回结果截断长度（防止 context 爆炸）。
        llm_kwargs: 透传给 LLM completion 的受控参数，例如 max_tokens / temperature。
        extra_metadata: 透传到 LangSmith LLM span 的业务观测字段。
    """

    max_iterations: int = 10
    max_tool_calls_per_turn: int = 5
    tool_timeout_s: int = 30
    task_type: str = TaskType.CHAT
    model: str = "primary"
    result_max_chars: int = 2000
    llm_kwargs: dict[str, Any] = field(default_factory=dict)
    tool_argument_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    tool_context: Any | None = None
    approved_tool_names: set[str] = field(default_factory=set)
    tool_choice: str | dict[str, Any] | None = None
    tool_event_handler: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None
    client_action_handler: Callable[[list[dict[str, Any]], dict[str, Any]], Awaitable[None] | None] | None = None
    terminal_client_action_types: set[str] = field(default_factory=lambda: {"ask_user_options"})
    extra_metadata: dict[str, Any] = field(default_factory=dict)


# ── 结果 ──────────────────────────────────────────────────────


@dataclass
class ToolCallRecord:
    """单次工具调用记录。"""

    tool_name: str
    arguments: dict[str, Any]
    result: str
    elapsed_s: float = 0.0
    success: bool = True
    error: str | None = None
    client_actions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class StreamingToolCall:
    """Tool call reconstructed from streaming delta chunks."""

    id: str
    type: str
    function_name: str
    arguments: str


@dataclass
class StreamingToolIteration:
    """One streamed assistant turn, including any requested tool calls."""

    content: str
    tool_calls: list[StreamingToolCall] = field(default_factory=list)


@dataclass
class AgentLoopResult:
    """Agent Loop 执行结果。"""

    final_answer: str
    iterations: int = 0
    tool_calls_made: list[ToolCallRecord] = field(default_factory=list)
    client_actions: list[dict[str, Any]] = field(default_factory=list)


# ── 核心函数 ──────────────────────────────────────────────────


async def run_agent_loop(
    messages: list[dict],
    *,
    tools: list[str] | None = None,
    config: AgentLoopConfig | None = None,
) -> AgentLoopResult:
    """执行 Agent Loop — 让 LLM 自主决定是否调用工具。

    这是外部模块调用 Agent Loop 的**唯一入口**。

    Args:
        messages: 初始消息列表（system + user 等）。
        tools: 可用工具名称列表。传 None 表示使用所有已注册工具。
            传空列表 [] 表示不暴露任何工具（等同于普通 acompletion）。
        config: 循环配置。不传则使用默认值。

    Returns:
        AgentLoopResult — 包含最终回答、迭代次数、工具调用记录。

    Example::

        from app.shared.infra.agent_loop import run_agent_loop
        result = await run_agent_loop(
            messages=[{"role": "user", "content": "什么是特征值？"}],
            tools=["search_kb"],
        )
        print(result.final_answer)
    """

    from app.shared.infra.llm_support import acompletion, acompletion_with_tools
    from app.shared.infra.tools.api import ensure_project_tool_modules_loaded
    from app.shared.infra.tools.registry import get_tool_registry

    cfg = config or AgentLoopConfig()
    ensure_project_tool_modules_loaded()
    registry = get_tool_registry()

    # 构建可用工具列表
    available_tools = _get_tool_definitions(registry, tools)
    if not available_tools:
        # 无可用工具 → 直接走普通补全（极简路径）
        answer = await acompletion(
            messages,
            task_type=cfg.task_type,
            model=cfg.model,
            extra_metadata=cfg.extra_metadata,
            **cfg.llm_kwargs,
        )
        return AgentLoopResult(final_answer=answer, iterations=1)

    all_tool_calls: list[ToolCallRecord] = []
    all_client_actions: list[dict[str, Any]] = []
    current_messages = list(messages)

    for iteration in range(1, cfg.max_iterations + 1):
        logger.info("agent_loop_iteration", iteration=iteration, max=cfg.max_iterations)

        # 1. 调用 LLM（带工具列表）
        response = await acompletion_with_tools(
            current_messages,
            tools=available_tools,
            task_type=cfg.task_type,
            model=cfg.model,
            extra_metadata=cfg.extra_metadata,
            **_tool_iteration_llm_kwargs(cfg, iteration),
        )

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)

        # 2. 没有 tool_calls → LLM 给出了最终回答
        if not tool_calls:
            if not (message.content or "").strip():
                logger.warning(
                    "agent_loop_empty_tool_response_fallback",
                    iteration=iteration,
                    model=cfg.model,
                    task_type=cfg.task_type,
                )
                fallback_answer = await acompletion(
                    current_messages,
                    task_type=cfg.task_type,
                    model=cfg.model,
                    extra_metadata={
                        **cfg.extra_metadata,
                        "agent_tool_stream_fallback": "empty_tool_response",
                    },
                    **cfg.llm_kwargs,
                )
                return AgentLoopResult(
                    final_answer=fallback_answer,
                    iterations=iteration,
                    tool_calls_made=all_tool_calls,
                    client_actions=all_client_actions,
                )
            return AgentLoopResult(
                final_answer=message.content or "",
                iterations=iteration,
                tool_calls_made=all_tool_calls,
                client_actions=all_client_actions,
            )

        # 3. 有 tool_calls → 执行工具，结果回传
        # 先将 assistant 的消息加入历史（包含 tool_calls 信息）
        current_messages.append(_assistant_msg_to_dict(message))

        for tool_call_index, tc in enumerate(tool_calls[: cfg.max_tool_calls_per_turn]):
            record = await _execute_one_tool(
                registry,
                tc,
                cfg,
                tool_call_index=tool_call_index,
            )
            all_tool_calls.append(record)
            all_client_actions.extend(record.client_actions)
            # 按 OpenAI 格式回传工具结果
            current_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": record.result,
            })
            if _has_terminal_client_action(record, cfg):
                return AgentLoopResult(
                    final_answer=message.content or "",
                    iterations=iteration,
                    tool_calls_made=all_tool_calls,
                    client_actions=all_client_actions,
                )

    # 安全阀：达到最大迭代次数
    logger.warning("agent_loop_max_iterations", max=cfg.max_iterations)

    # 最后一轮强制普通补全获取回答
    final_answer = await acompletion(
        current_messages,
        task_type=cfg.task_type,
        model=cfg.model,
        extra_metadata=cfg.extra_metadata,
        **cfg.llm_kwargs,
    )
    return AgentLoopResult(
        final_answer=final_answer,
        iterations=cfg.max_iterations,
        tool_calls_made=all_tool_calls,
        client_actions=all_client_actions,
    )


async def run_agent_loop_stream(
    messages: list[dict],
    *,
    tools: list[str] | None = None,
    config: AgentLoopConfig | None = None,
) -> AsyncGenerator[str, None]:
    """Stream an agent turn while allowing the model to request tools mid-stream."""

    from app.shared.infra.llm_support import acompletion_stream
    from app.shared.infra.tools.api import ensure_project_tool_modules_loaded
    from app.shared.infra.tools.registry import get_tool_registry

    cfg = config or AgentLoopConfig()
    ensure_project_tool_modules_loaded()
    registry = get_tool_registry()

    available_tools = _get_tool_definitions(registry, tools)
    if not available_tools:
        async for chunk in acompletion_stream(
            messages,
            task_type=cfg.task_type,
            model=cfg.model,
            extra_metadata=cfg.extra_metadata,
            **cfg.llm_kwargs,
        ):
            yield chunk
        return

    current_messages = list(messages)

    for iteration in range(1, cfg.max_iterations + 1):
        logger.info("agent_loop_stream_iteration", iteration=iteration, max=cfg.max_iterations)
        streamed: StreamingToolIteration | None = None
        async for event in _stream_one_tool_iteration(
            current_messages,
            tools=available_tools,
            cfg=cfg,
            tool_choice=cfg.tool_choice if iteration == 1 else None,
        ):
            if isinstance(event, StreamingToolIteration):
                streamed = event
            else:
                yield event

        if streamed is None:
            return
        if not streamed.tool_calls:
            if not streamed.content.strip():
                logger.warning(
                    "agent_loop_stream_empty_tool_response_fallback",
                    iteration=iteration,
                    model=cfg.model,
                    task_type=cfg.task_type,
                )
                async for chunk in acompletion_stream(
                    current_messages,
                    task_type=cfg.task_type,
                    model=cfg.model,
                    extra_metadata={
                        **cfg.extra_metadata,
                        "agent_tool_stream_fallback": "empty_tool_response",
                    },
                    **cfg.llm_kwargs,
                ):
                    yield chunk
            return

        current_messages.append(_streaming_assistant_msg_to_dict(streamed))
        for tool_call_index, tc in enumerate(streamed.tool_calls[: cfg.max_tool_calls_per_turn]):
            record = await _execute_one_tool(
                registry,
                tc,
                cfg,
                tool_call_index=tool_call_index,
            )
            current_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": record.result,
            })
            if _has_terminal_client_action(record, cfg):
                return

    logger.warning("agent_loop_stream_max_iterations", max=cfg.max_iterations)
    async for chunk in acompletion_stream(
        current_messages,
        task_type=cfg.task_type,
        model=cfg.model,
        extra_metadata=cfg.extra_metadata,
        **cfg.llm_kwargs,
    ):
        yield chunk


# ---------------- internal helpers ----------------


async def _stream_one_tool_iteration(
    messages: list[dict],
    *,
    tools: list[dict],
    cfg: AgentLoopConfig,
    tool_choice: str | dict[str, Any] | None = None,
) -> AsyncGenerator[str | StreamingToolIteration, None]:
    """Stream one assistant turn and reconstruct tool calls from deltas."""

    from app.shared.infra.exceptions import LLMCallError, LLMTimeoutError
    from app.shared.infra.llm_support.common import (
        build_completion_contexts,
        context_request_timeout_s,
        effective_call_timeout_s,
        extract_usage,
        get_llm_concurrency_limiter,
        log_attempt_cancelled,
        log_attempt_failed,
        log_attempt_started,
        log_attempt_timeout,
        merge_usage,
        prepare_completion_attempt,
        track_call,
    )
    from app.shared.infra.llm_support.litellm_loader import load_litellm
    from app.shared.infra.llm_support.observability import (
        _end_langsmith_trace,
        _langsmith_trace_kwargs,
        _record_new_token_event,
        llm_api_mode_outputs,
    )
    from app.shared.infra.llm_support.stream import _stream_chunks_with_timeout
    from app.shared.infra.observability.trace import langsmith_trace

    litellm = load_litellm()
    contexts = build_completion_contexts(task_type=cfg.task_type, model=cfg.model)
    start = time.monotonic()
    tracked_model = contexts[0].model
    last_error: Exception | None = None

    async with get_llm_concurrency_limiter():
        for attempt_number, context in enumerate(contexts, start=1):
            prepared = prepare_completion_attempt(
                context=context,
                messages=messages,
                extra_kwargs=without_provider_native_tools(cfg.llm_kwargs),
                attempt=attempt_number,
                override_kwargs=_tool_stream_override_kwargs_with_choice(tools, tool_choice),
            )
            attempt_streamed_content = False
            try:
                tracked_model = prepared.tracked_model
                log_attempt_started(
                    "llm_tools_stream_started",
                    attempt=prepared,
                    context=context,
                    extra={
                        "tool_count": len(tools),
                        "api_mode": "chat_completions",
                    },
                )
                usage = (0, 0, 0)
                content_parts: list[str] = []
                tool_call_parts: dict[int, dict[str, str]] = {}
                first_token_seen = False
                trace_metadata = {
                    **dict(cfg.extra_metadata or {}),
                    "llm_requested_api_mode": str(
                        cfg.llm_kwargs.get("api_mode") or context.settings.llm.api_mode
                    ),
                    "llm_api_mode_route_reason": "project_function_tools_stream_chat_completions",
                }
                with langsmith_trace(
                    name="LLM: stream with tools",
                    run_type="llm",
                    **_langsmith_trace_kwargs(
                        task_type=context.task_type,
                        call_model=prepared.call_model,
                        provider=prepared.provider,
                        model_name=tracked_model,
                        mode="tools_stream_chat_completions",
                        messages=messages,
                        call_kwargs=prepared.call_kwargs,
                        tools=tools,
                        endpoint_role=context.endpoint_role,
                        model_selector=context.model_selector,
                        extra_metadata=trace_metadata,
                    ),
                ) as trace_run:
                    response = await asyncio.wait_for(
                        litellm.acompletion(**prepared.call_kwargs),
                        timeout=context_request_timeout_s(context, prepared.call_kwargs),
                    )
                    usage = merge_usage(usage, extract_usage(response))
                    async for chunk in _stream_chunks_with_timeout(
                        response,
                        timeout_s=context_request_timeout_s(context, prepared.call_kwargs),
                    ):
                        usage = merge_usage(usage, extract_usage(chunk))
                        choices = getattr(chunk, "choices", None) or []
                        if not choices:
                            continue
                        delta = getattr(choices[0], "delta", None)
                        if delta is None:
                            continue
                        content = getattr(delta, "content", None)
                        if content:
                            if not first_token_seen:
                                _record_new_token_event(trace_run)
                                first_token_seen = True
                            content_parts.append(content)
                            attempt_streamed_content = True
                            yield content
                        _accumulate_streaming_tool_calls(
                            tool_call_parts,
                            getattr(delta, "tool_calls", None),
                        )
                    tool_calls = _finalize_streaming_tool_calls(tool_call_parts)
                    prompt_t, completion_t, total_t = usage
                    _end_langsmith_trace(
                        trace_run,
                        text="".join(content_parts),
                        tool_calls=[
                            {
                                "id": item.id,
                                "type": item.type,
                                "function": {
                                    "name": item.function_name,
                                    "arguments": item.arguments,
                                },
                            }
                            for item in tool_calls
                        ],
                        extra_outputs=llm_api_mode_outputs(
                            initial_api_mode="chat_completions",
                            final_api_mode="chat_completions",
                            final_route_reason="project_function_tools_stream_chat_completions",
                        ),
                        prompt_tokens=prompt_t,
                        completion_tokens=completion_t,
                        total_tokens=total_t,
                    )
                logger.info(
                    "llm_tools_stream_complete",
                    elapsed_s=round(time.monotonic() - start, 2),
                    model=tracked_model,
                    task_type=context.task_type,
                    endpoint_role=context.endpoint_role,
                    has_tool_calls=bool(tool_calls),
                    api_mode="chat_completions",
                )
                prompt_t, completion_t, total_t = usage
                track_call(
                    task_type=context.task_type,
                    model=tracked_model,
                    start=start,
                    success=True,
                    prompt_tokens=prompt_t,
                    completion_tokens=completion_t,
                    total_tokens=total_t,
                )
                yield StreamingToolIteration(content="".join(content_parts), tool_calls=tool_calls)
                return
            except asyncio.TimeoutError:
                last_error = LLMTimeoutError(
                    timeout_s=effective_call_timeout_s(context, prepared.call_kwargs)
                )
                log_attempt_timeout("llm_tools_stream_timeout", attempt=prepared, context=context)
                track_call(
                    task_type=context.task_type,
                    model=tracked_model,
                    start=start,
                    success=False,
                    error="timeout",
                )
                if attempt_streamed_content:
                    raise last_error
            except asyncio.CancelledError:
                log_attempt_cancelled("llm_tools_stream_cancelled", attempt=prepared, context=context)
                track_call(
                    task_type=context.task_type,
                    model=tracked_model,
                    start=start,
                    success=False,
                    error="cancelled",
                )
                raise
            except Exception as exc:
                last_error = exc
                track_call(
                    task_type=context.task_type,
                    model=tracked_model,
                    start=start,
                    success=False,
                    error=str(exc),
                )
                log_attempt_failed(
                    "llm_tools_stream_failed",
                    attempt=prepared,
                    context=context,
                    error=exc,
                    level="error",
                )
                if attempt_streamed_content:
                    raise LLMCallError(reason=str(exc)) from exc

    if isinstance(last_error, LLMTimeoutError):
        raise last_error
    if last_error is not None:
        raise LLMCallError(reason=str(last_error)) from last_error


def _accumulate_streaming_tool_calls(
    parts: dict[int, dict[str, str]],
    deltas: object,
) -> None:
    if not deltas:
        return
    for fallback_index, delta in enumerate(deltas):
        index = _coerce_int(_get_attr_or_key(delta, "index"), fallback=fallback_index)
        item = parts.setdefault(
            index,
            {"id": "", "type": "function", "name": "", "arguments": ""},
        )
        call_id = _get_attr_or_key(delta, "id")
        if call_id:
            item["id"] = str(call_id)
        call_type = _get_attr_or_key(delta, "type")
        if call_type:
            item["type"] = str(call_type)
        function = _get_attr_or_key(delta, "function")
        if function is None:
            continue
        function_name = _get_attr_or_key(function, "name")
        if function_name:
            item["name"] += str(function_name)
        arguments = _get_attr_or_key(function, "arguments")
        if arguments:
            item["arguments"] += str(arguments)


def _finalize_streaming_tool_calls(parts: dict[int, dict[str, str]]) -> list[StreamingToolCall]:
    tool_calls: list[StreamingToolCall] = []
    for index in sorted(parts):
        item = parts[index]
        function_name = item.get("name", "").strip()
        if not function_name:
            continue
        tool_calls.append(
            StreamingToolCall(
                id=item.get("id", "").strip() or f"call_{index}",
                type=item.get("type", "").strip() or "function",
                function_name=function_name,
                arguments=item.get("arguments", ""),
            )
        )
    return tool_calls


def _streaming_assistant_msg_to_dict(iteration: StreamingToolIteration) -> dict:
    msg: dict = {"role": "assistant", "content": iteration.content or ""}
    if iteration.tool_calls:
        msg["tool_calls"] = [
            {
                "id": item.id,
                "type": item.type or "function",
                "function": {
                    "name": item.function_name,
                    "arguments": item.arguments,
                },
            }
            for item in iteration.tool_calls
        ]
    return msg


def _tool_stream_override_kwargs(tools: list[dict]) -> dict[str, Any]:
    return _tool_stream_override_kwargs_with_choice(tools)


def _tool_stream_override_kwargs_with_choice(
    tools: list[dict],
    tool_choice: str | dict[str, Any] | None = None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "stream": True,
        "tools": tools,
        "parallel_tool_calls": False,
    }
    normalized_choice = _normalize_tool_choice(tool_choice)
    if normalized_choice is not None:
        kwargs["tool_choice"] = normalized_choice
    return kwargs


def _tool_iteration_llm_kwargs(cfg: AgentLoopConfig, iteration: int) -> dict[str, Any]:
    kwargs = without_provider_native_tools(cfg.llm_kwargs)
    if iteration == 1:
        normalized_choice = _normalize_tool_choice(cfg.tool_choice)
        if normalized_choice is not None:
            kwargs["tool_choice"] = normalized_choice
    return kwargs


def _normalize_tool_choice(tool_choice: str | dict[str, Any] | None) -> dict[str, Any] | str | None:
    if tool_choice is None:
        return None
    if isinstance(tool_choice, dict):
        return tool_choice
    name = str(tool_choice).strip()
    if not name:
        return None
    if name in {"auto", "none", "required"}:
        return name
    return {"type": "function", "function": {"name": name}}


def _get_attr_or_key(value: object, key: str) -> object:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _coerce_int(value: object, *, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _get_tool_definitions(registry, tool_names: list[str] | None) -> list[dict]:
    """获取工具定义列表（OpenAI 格式）。"""

    all_defs = registry.to_openai_format()
    if tool_names is None:
        return all_defs
    name_set = set(tool_names)
    return [d for d in all_defs if d["function"]["name"] in name_set]


def _assistant_msg_to_dict(message) -> dict:
    """将 LiteLLM 的 assistant message 转为 dict（含 tool_calls）。"""

    msg: dict = {"role": "assistant", "content": message.content or ""}
    if message.tool_calls:
        msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]
    return msg


async def _execute_one_tool(
    registry,
    tool_call,
    cfg: AgentLoopConfig,
    *,
    tool_call_index: int | None = None,
) -> ToolCallRecord:
    """执行一次工具调用并返回记录。"""

    function = getattr(tool_call, "function", None)
    func_name = str(
        getattr(function, "name", None)
        or getattr(tool_call, "function_name", "")
    )
    tool_call_id = str(getattr(tool_call, "id", "") or "")
    tool_definition = registry.get(func_name)
    hidden_arg_names = list(getattr(tool_definition, "hidden_args", []) or [])
    raw_arguments = (
        getattr(function, "arguments", None)
        if function is not None
        else None
    )
    if raw_arguments is None:
        raw_arguments = getattr(tool_call, "arguments", "")
    try:
        args = json.loads(raw_arguments)
    except (json.JSONDecodeError, TypeError):
        args = {}
    if not isinstance(args, dict):
        args = {}
    visible_args = dict(args)
    context_args = _resolve_context_tool_args(
        cfg.tool_context,
        tool_name=func_name,
        hidden_args=hidden_arg_names,
    )
    injected_args = dict(cfg.tool_argument_overrides.get(func_name, {}) or {})
    if context_args or injected_args:
        args = {
            **args,
            **context_args,
            **injected_args,
        }
    trace_metadata = {
        "agent_task_type": cfg.task_type,
        "agent_model_selector": cfg.model,
        "agent_tool_timeout_s": cfg.tool_timeout_s,
        "agent_tool_result_max_chars": cfg.result_max_chars,
        "tool_call_id": tool_call_id,
        "tool_call_index": tool_call_index,
        "tool_visible_argument_names": sorted(str(name) for name in visible_args),
        "tool_context_argument_names": sorted(str(name) for name in context_args),
        "tool_injected_argument_names": sorted(str(name) for name in injected_args),
        "tool_hidden_argument_names": sorted(
            str(name)
            for name in hidden_arg_names
            if name in args or name in context_args or name in injected_args
        ),
    }

    start = time.monotonic()
    await _emit_tool_event(
        cfg,
        phase="started",
        tool_name=func_name,
        tool_call_id=tool_call_id,
        argument_names=sorted(str(name) for name in visible_args.keys()),
    )
    try:
        raw_result = await asyncio.wait_for(
            registry.execute(
                func_name,
                _approval_granted=_is_tool_approved(cfg.tool_context, func_name)
                or func_name in cfg.approved_tool_names,
                _trace_metadata=trace_metadata,
                **args,
            ),
            timeout=cfg.tool_timeout_s,
        )
        client_actions = _extract_tool_client_actions(raw_result)
        if client_actions:
            await _emit_client_actions(
                cfg,
                client_actions,
                tool_name=func_name,
                tool_call_id=tool_call_id,
            )
        result_str = str(raw_result)[: cfg.result_max_chars]
        elapsed = round(time.monotonic() - start, 3)
        logger.info(
            "tool_executed",
            tool=func_name,
            elapsed_s=elapsed,
            result_len=len(result_str),
        )
        await _emit_tool_event(
            cfg,
            phase="completed",
            tool_name=func_name,
            tool_call_id=tool_call_id,
            elapsed_s=elapsed,
            success=True,
        )
        return ToolCallRecord(
            tool_name=func_name,
            arguments=args,
            result=result_str,
            elapsed_s=elapsed,
            client_actions=client_actions,
        )
    except asyncio.TimeoutError:
        elapsed = round(time.monotonic() - start, 3)
        error_msg = f"工具 `{func_name}` 执行超时（{cfg.tool_timeout_s}s）"
        logger.warning("tool_timeout", tool=func_name, timeout_s=cfg.tool_timeout_s)
        await _emit_tool_event(
            cfg,
            phase="failed",
            tool_name=func_name,
            tool_call_id=tool_call_id,
            elapsed_s=elapsed,
            success=False,
            error=error_msg,
        )
        return ToolCallRecord(
            tool_name=func_name,
            arguments=args,
            result=error_msg,
            elapsed_s=elapsed,
            success=False,
            error=error_msg,
        )
    except Exception as exc:
        elapsed = round(time.monotonic() - start, 3)
        error_msg = f"工具 `{func_name}` 执行失败：{exc}"
        logger.warning("tool_failed", tool=func_name, error=str(exc))
        await _emit_tool_event(
            cfg,
            phase="failed",
            tool_name=func_name,
            tool_call_id=tool_call_id,
            elapsed_s=elapsed,
            success=False,
            error=str(exc),
        )
        return ToolCallRecord(
            tool_name=func_name,
            arguments=args,
            result=error_msg,
            elapsed_s=elapsed,
            success=False,
            error=str(exc),
        )


async def _emit_tool_event(cfg: AgentLoopConfig, **payload: Any) -> None:
    handler = cfg.tool_event_handler
    if handler is None:
        return
    try:
        result = handler(payload)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # noqa: BLE001
        logger.debug("tool_event_handler_failed", error=str(exc))


async def _emit_client_actions(
    cfg: AgentLoopConfig,
    client_actions: list[dict[str, Any]],
    **metadata: Any,
) -> None:
    handler = cfg.client_action_handler
    if handler is None or not client_actions:
        return
    try:
        result = handler(client_actions, metadata)
        if inspect.isawaitable(result):
            await result
    except Exception as exc:  # noqa: BLE001
        logger.debug("client_action_handler_failed", error=str(exc))


def _extract_tool_client_actions(raw_result: Any) -> list[dict[str, Any]]:
    payload = raw_result
    if hasattr(raw_result, "to_dict") and callable(raw_result.to_dict):
        try:
            payload = raw_result.to_dict()
        except Exception:  # noqa: BLE001
            payload = raw_result
    if not isinstance(payload, Mapping):
        return []
    actions = payload.get("client_actions")
    if not isinstance(actions, list):
        return []
    normalized: list[dict[str, Any]] = []
    for action in actions:
        if not isinstance(action, Mapping):
            continue
        action_type = str(action.get("type") or "").strip()
        if not action_type:
            continue
        payload_value = action.get("payload")
        normalized.append(
            {
                "type": action_type,
                "payload": dict(payload_value) if isinstance(payload_value, Mapping) else {},
            }
        )
    return normalized


def _has_terminal_client_action(record: ToolCallRecord, cfg: AgentLoopConfig) -> bool:
    terminal_types = {str(item).strip() for item in cfg.terminal_client_action_types if str(item).strip()}
    if not terminal_types:
        return False
    return any(str(action.get("type") or "").strip() in terminal_types for action in record.client_actions)


def _resolve_context_tool_args(
    tool_context: Any | None,
    *,
    tool_name: str,
    hidden_args: list[str],
) -> dict[str, Any]:
    if tool_context is None or not hidden_args:
        return {}
    if hasattr(tool_context, "tool_arguments_for"):
        resolved = tool_context.tool_arguments_for(
            tool_name=tool_name,
            hidden_args=hidden_args,
        )
        return dict(resolved or {})
    if isinstance(tool_context, Mapping):
        return {
            name: tool_context[name]
            for name in hidden_args
            if name in tool_context and tool_context[name] is not None
        }
    return {
        name: getattr(tool_context, name)
        for name in hidden_args
        if hasattr(tool_context, name) and getattr(tool_context, name) is not None
    }


def _is_tool_approved(tool_context: Any | None, tool_name: str) -> bool:
    if tool_context is None:
        return False
    if hasattr(tool_context, "is_tool_approved"):
        return bool(tool_context.is_tool_approved(tool_name))
    approved_tool_names = getattr(tool_context, "approved_tool_names", None)
    return tool_name in set(approved_tool_names or ())
