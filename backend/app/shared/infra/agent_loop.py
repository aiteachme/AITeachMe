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
    tool_event_handler: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None
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


@dataclass
class AgentLoopResult:
    """Agent Loop 执行结果。"""

    final_answer: str
    iterations: int = 0
    tool_calls_made: list[ToolCallRecord] = field(default_factory=list)


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
            **cfg.llm_kwargs,
        )

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)

        # 2. 没有 tool_calls → LLM 给出了最终回答
        if not tool_calls:
            return AgentLoopResult(
                final_answer=message.content or "",
                iterations=iteration,
                tool_calls_made=all_tool_calls,
            )

        # 3. 有 tool_calls → 执行工具，结果回传
        # 先将 assistant 的消息加入历史（包含 tool_calls 信息）
        current_messages.append(_assistant_msg_to_dict(message))

        for tc in tool_calls[: cfg.max_tool_calls_per_turn]:
            record = await _execute_one_tool(registry, tc, cfg)
            all_tool_calls.append(record)
            # 按 OpenAI 格式回传工具结果
            current_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": record.result,
            })

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
    )


async def run_agent_loop_stream(
    messages: list[dict],
    *,
    tools: list[str] | None = None,
    config: AgentLoopConfig | None = None,
) -> AsyncGenerator[str, None]:
    """流式 Agent Loop — 工具调用阶段静默，最终回答阶段流式输出。

    适用于 Interact 伴读引擎等需要实时响应的场景。

    Args:
        messages: 初始消息列表。
        tools: 可用工具名称列表。
        config: 循环配置。

    Yields:
        str — 最终回答的文本片段。

    Example::

        from app.shared.infra.agent_loop import run_agent_loop_stream
        async for chunk in run_agent_loop_stream(messages, tools=["search_kb"]):
            print(chunk, end="")
    """

    from app.shared.infra.llm_support import acompletion_stream, acompletion_with_tools
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
        # 非流式调用以检测 tool_calls
        response = await acompletion_with_tools(
            current_messages,
            tools=available_tools,
            task_type=cfg.task_type,
            model=cfg.model,
            extra_metadata=cfg.extra_metadata,
            **cfg.llm_kwargs,
        )

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)

        if not tool_calls:
            # 工具选择使用非流式调用；最终回答必须重新走流式补全，保证前端拿到真实 token SSE。
            async for chunk in acompletion_stream(
                current_messages,
                task_type=cfg.task_type,
                model=cfg.model,
                extra_metadata=cfg.extra_metadata,
                **cfg.llm_kwargs,
            ):
                yield chunk
            return

        # 执行工具
        current_messages.append(_assistant_msg_to_dict(message))
        for tc in tool_calls[: cfg.max_tool_calls_per_turn]:
            record = await _execute_one_tool(registry, tc, cfg)
            current_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": record.result,
            })

    # 安全阀 → 流式获取最终回答
    async for chunk in acompletion_stream(
        current_messages,
        task_type=cfg.task_type,
        model=cfg.model,
        extra_metadata=cfg.extra_metadata,
        **cfg.llm_kwargs,
    ):
        yield chunk


# ── 内部辅助函数 ──────────────────────────────────────────────


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


async def _execute_one_tool(registry, tool_call, cfg: AgentLoopConfig) -> ToolCallRecord:
    """执行一次工具调用并返回记录。"""

    func_name = tool_call.function.name
    tool_definition = registry.get(func_name)
    try:
        args = json.loads(tool_call.function.arguments)
    except (json.JSONDecodeError, TypeError):
        args = {}
    if not isinstance(args, dict):
        args = {}
    visible_args = dict(args)
    context_args = _resolve_context_tool_args(
        cfg.tool_context,
        tool_name=func_name,
        hidden_args=list(getattr(tool_definition, "hidden_args", []) or []),
    )
    injected_args = dict(cfg.tool_argument_overrides.get(func_name, {}) or {})
    if context_args or injected_args:
        args = {
            **args,
            **context_args,
            **injected_args,
        }

    start = time.monotonic()
    await _emit_tool_event(
        cfg,
        phase="started",
        tool_name=func_name,
        tool_call_id=str(getattr(tool_call, "id", "") or ""),
        argument_names=sorted(str(name) for name in visible_args.keys()),
    )
    try:
        raw_result = await asyncio.wait_for(
            registry.execute(
                func_name,
                _approval_granted=_is_tool_approved(cfg.tool_context, func_name)
                or func_name in cfg.approved_tool_names,
                **args,
            ),
            timeout=cfg.tool_timeout_s,
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
            tool_call_id=str(getattr(tool_call, "id", "") or ""),
            elapsed_s=elapsed,
            success=True,
        )
        return ToolCallRecord(
            tool_name=func_name,
            arguments=args,
            result=result_str,
            elapsed_s=elapsed,
        )
    except asyncio.TimeoutError:
        elapsed = round(time.monotonic() - start, 3)
        error_msg = f"工具 `{func_name}` 执行超时（{cfg.tool_timeout_s}s）"
        logger.warning("tool_timeout", tool=func_name, timeout_s=cfg.tool_timeout_s)
        await _emit_tool_event(
            cfg,
            phase="failed",
            tool_name=func_name,
            tool_call_id=str(getattr(tool_call, "id", "") or ""),
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
            tool_call_id=str(getattr(tool_call, "id", "") or ""),
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
