"""工具注册表。"""
from __future__ import annotations
import asyncio, json
from typing import Any
import structlog
from app.core.tools.definition import ToolDefinition

logger = structlog.get_logger()

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool_def: ToolDefinition) -> None:
        self._tools[tool_def.name] = tool_def
        logger.info("tool_registered", name=tool_def.name, engines=tool_def.engines)

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def get_tools_for_engine(self, engine: str) -> list[ToolDefinition]:
        return [t for t in self._tools.values() if not t.engines or engine in t.engines]

    def to_openai_format(self, engine: str | None = None) -> list[dict]:
        tools = self.get_tools_for_engine(engine) if engine else list(self._tools.values())
        return [t.to_openai_format() for t in tools]

    async def execute(self, name: str, **kwargs: Any) -> Any:
        td = self._tools.get(name)
        if td is None:
            raise ValueError(f"工具 `{name}` 未注册")
        logger.info("tool_executing", name=name)
        if td.is_async:
            return await td.handler(**kwargs)
        return await asyncio.to_thread(td.handler, **kwargs)

    async def execute_tool_call(self, tool_call: dict) -> str:
        func = tool_call.get("function", {})
        name = func.get("name", "")
        try:
            args = json.loads(func.get("arguments", "{}"))
        except json.JSONDecodeError:
            args = {}
        result = await self.execute(name, **args)
        return str(result)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

_registry: ToolRegistry | None = None

def get_tool_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
