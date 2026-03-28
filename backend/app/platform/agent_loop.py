"""Agent Loop — 工具增强的 LLM 推理循环。

实现 ReAct 模式：Reason → Act (tool call) → Observe → Repeat。

对外只需一行调用::

    from app.platform.agent_loop import run_agent_loop
    result = await run_agent_loop(messages, tools=["search_kb"])
    answer = result.final_answer
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

import structlog

from app.platform.model_router import TaskType
from app.infra.tracing import get_tracer

logger = structlog.get_logger()

# ── 配置 ──────────────────────────────────────────────────────


@dataclass
class AgentLoopConfig:
    """Agent Loop 配置。

    Attributes:
        max_iterations: 最大循环次数（安全阀，防止无限循环）。
        max_tool_calls_per_turn: 同一轮 LLM 响应中最多执行几个工具调用。
        tool_timeout_s: 单个工具执行超时（秒）。
        task_type: 任务类型，影响模型路由。
        result_max_chars: 工具返回结果截断长度（防止 context 爆炸）。
    """

    max_iterations: int = 10
    max_tool_calls_per_turn: int = 5
    tool_timeout_s: int = 30
    task_type: TaskType = TaskType.CHAT
    result_max_chars: int = 2000


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

        from app.platform.agent_loop import run_agent_loop
        result = await run_agent_loop(
            messages=[{"role": "user", "content": "什么是特征值？"}],
            tools=["search_kb"],
        )
        print(result.final_answer)
    """

    from app.platform.llm import acompletion, acompletion_with_tools
    from app.platform.tools.registry import get_tool_registry

    cfg = config or AgentLoopConfig()
    registry = get_tool_registry()
    tracer = get_tracer()
    span = tracer.start_span("agent_loop")

    # 构建可用工具列表
    available_tools = _get_tool_definitions(registry, tools)
    if not available_tools:
        # 无可用工具 → 直接走普通补全（极简路径）
        answer = await acompletion(messages, task_type=cfg.task_type)
        tracer.end_span(span.span_id)
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
        )

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)

        # 2. 没有 tool_calls → LLM 给出了最终回答
        if not tool_calls:
            tracer.end_span(span.span_id)
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
    tracer.end_span(span.span_id)

    # 最后一轮强制普通补全获取回答
    final_answer = await acompletion(current_messages, task_type=cfg.task_type)
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

        from app.platform.agent_loop import run_agent_loop_stream
        async for chunk in run_agent_loop_stream(messages, tools=["search_kb"]):
            print(chunk, end="")
    """

    from app.platform.llm import acompletion_stream, acompletion_with_tools
    from app.platform.tools.registry import get_tool_registry

    cfg = config or AgentLoopConfig()
    registry = get_tool_registry()

    available_tools = _get_tool_definitions(registry, tools)
    if not available_tools:
        async for chunk in acompletion_stream(messages, task_type=cfg.task_type):
            yield chunk
        return

    current_messages = list(messages)

    for iteration in range(1, cfg.max_iterations + 1):
        # 非流式调用以检测 tool_calls
        response = await acompletion_with_tools(
            current_messages,
            tools=available_tools,
            task_type=cfg.task_type,
        )

        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)

        if not tool_calls:
            # 最后一轮没有工具调用 → 此结果就是最终回答
            # 但我们已经用非流式拿到了，需要把内容 yield 出去
            if message.content:
                yield message.content
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
    async for chunk in acompletion_stream(current_messages, task_type=cfg.task_type):
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
    try:
        args = json.loads(tool_call.function.arguments)
    except (json.JSONDecodeError, TypeError):
        args = {}

    start = time.monotonic()
    try:
        raw_result = await asyncio.wait_for(
            registry.execute(func_name, **args),
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
        return ToolCallRecord(
            tool_name=func_name,
            arguments=args,
            result=error_msg,
            elapsed_s=elapsed,
            success=False,
            error=str(exc),
        )
