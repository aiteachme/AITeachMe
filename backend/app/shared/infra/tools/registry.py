"""工具注册表。"""
from __future__ import annotations
import asyncio
import json
from typing import Any
import structlog
from app.shared.infra.tools.definition import ToolDefinition

logger = structlog.get_logger()


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
        if td.is_async:
            return await td.handler(**kwargs)
        return await asyncio.to_thread(td.handler, **kwargs)

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
