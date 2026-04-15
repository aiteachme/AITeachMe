"""工具注册表。"""
from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

import structlog

from app.shared.infra.observability.trace import (
    sanitize_langsmith_input,
    sanitize_langsmith_output,
    traceable_with_context,
)
from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.execution.security import check_action_safety

logger = structlog.get_logger()


def _tool_result_summary(result: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "result_type": type(result).__name__,
    }
    if isinstance(result, dict):
        summary["result_keys"] = sorted(str(key) for key in list(result.keys())[:6])
    elif isinstance(result, (list, tuple, set)):
        summary["item_count"] = len(result)
    return summary


def _tool_trace_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(inputs.get("tool_name") or ""),
        "arguments": sanitize_langsmith_input(
            dict(inputs.get("arguments") or {}),
            field_name="arguments",
        ),
    }


def _tool_trace_outputs(payload: object) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    trace = payload.get("trace")
    if isinstance(trace, Mapping):
        return dict(trace)
    return {}


def _tool_trace_metadata(
    _registry: "ToolRegistry",
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    tool_definition: ToolDefinition,
    **_: Any,
) -> dict[str, Any]:
    del arguments
    return {
        "tool_name": tool_name,
        "tool_source": tool_definition.source,
        "tool_tags": list(tool_definition.tags),
        "tool_is_async": tool_definition.is_async,
    }


def _tool_trace_tags(
    _registry: "ToolRegistry",
    *,
    tool_name: str,
    arguments: Mapping[str, Any],
    tool_definition: ToolDefinition,
    **_: Any,
) -> list[str]:
    del arguments
    return [f"tool:{tool_name}", *[f"tool_tag:{tag}" for tag in list(tool_definition.tags)[:5]]]


class ToolRegistry:
    """管理工具的注册、查询、执行。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, td: ToolDefinition) -> None:
        self._tools[td.name] = td
        logger.info("tool_registered", name=td.name, tags=td.tags, source=td.source)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def to_openai_format(self) -> list[dict]:
        return [t.to_openai_format() for t in self._tools.values()]

    def list_all(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    @traceable_with_context(
        name="tool.execute",
        run_type="tool",
        process_inputs=_tool_trace_inputs,
        process_outputs=_tool_trace_outputs,
        name_factory=lambda self, *, tool_name, **_: f"tool.{tool_name}",
        metadata_factory=_tool_trace_metadata,
        tags_factory=_tool_trace_tags,
    )
    async def _run_traced_tool(
        self,
        *,
        tool_name: str,
        arguments: Mapping[str, Any],
        tool_definition: ToolDefinition,
        approval_granted: bool = False,
        langsmith_extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del langsmith_extra
        decision = await check_action_safety(tool_name, dict(arguments))
        if not decision.allowed:
            raise PermissionError(decision.reason or f"工具 `{tool_name}` 被安全策略拦截")
        if (tool_definition.requires_approval or decision.requires_user_confirm) and not approval_granted:
            raise PermissionError(f"工具 `{tool_name}` 需要用户确认后才能执行")
        if tool_definition.is_async:
            result = await tool_definition.handler(**dict(arguments))
        else:
            result = await asyncio.to_thread(tool_definition.handler, **dict(arguments))
        return {
            "result": result,
            "trace": {
                "success": True,
                **sanitize_langsmith_output(_tool_result_summary(result), field_name="result_summary"),
            },
        }

    async def execute(self, name: str, _approval_granted: bool = False, **kwargs: Any) -> Any:
        td = self._tools.get(name)
        if td is None:
            raise ValueError(f"工具 `{name}` 未注册")
        payload = await self._run_traced_tool(
            tool_name=name,
            arguments=dict(kwargs),
            tool_definition=td,
            approval_granted=_approval_granted,
        )
        return payload["result"]

    async def execute_tool_call(self, tool_call: dict) -> str:
        """执行 OpenAI 格式的 tool_call。"""
        func = tool_call.get("function", {})
        args = json.loads(func.get("arguments", "{}"))
        return str(await self.execute(func.get("name", ""), **args))

    @property
    def names(self) -> list[str]:
        return list(self._tools.keys())


_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
