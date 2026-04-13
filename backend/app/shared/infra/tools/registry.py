"""工具注册表。"""
from __future__ import annotations
import asyncio
import json
from collections.abc import Mapping
from typing import Any
import structlog
from app.shared.infra.config import get_settings
from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tracing import get_llm_trace_context, langsmith_trace

logger = structlog.get_logger()


def _serialize_trace_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _serialize_trace_value(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, (list, tuple, set)):
        return [_serialize_trace_value(item) for item in value]
    if isinstance(value, (str, bytes)):
        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
        limit = max(32, int(get_settings().langsmith_max_text_chars))
        if len(text) <= limit:
            return text
        return f"{text[: max(1, limit - 3)]}..."
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _serialize_trace_value(str(value))


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

    async def execute(self, name: str, **kwargs: Any) -> Any:
        td = self._tools.get(name)
        if td is None:
            raise ValueError(f"工具 `{name}` 未注册")
        trace_context = get_llm_trace_context()
        trace_inputs = {
            "name": name,
            "arguments": _serialize_trace_value(kwargs),
        }
        trace_tags = [f"tool:{name}", *[f"tool_tag:{tag}" for tag in list(td.tags)[:5]]]
        trace_metadata = {
            "tool_name": name,
            "tool_source": td.source,
            "tool_tags": list(td.tags),
            "tool_is_async": td.is_async,
        }
        with langsmith_trace(
            name=f"tool.{name}",
            run_type="tool",
            inputs=trace_inputs,
            subject=trace_context.subject,
            build_session_id=trace_context.build_session_id,
            workflow=trace_context.workflow,
            lane=trace_context.lane,
            node=trace_context.node,
            extra_metadata=trace_metadata,
            extra_tags=trace_tags,
        ) as run:
            try:
                if td.is_async:
                    result = await td.handler(**kwargs)
                else:
                    result = await asyncio.to_thread(td.handler, **kwargs)
            except Exception as exc:
                if run is not None:
                    run.end(
                        outputs={
                            "success": False,
                            "error": _serialize_trace_value(str(exc)),
                        }
                    )
                raise
            if run is not None:
                run.end(
                    outputs={
                        "success": True,
                        "result": _serialize_trace_value(result),
                    }
                )
            return result

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
