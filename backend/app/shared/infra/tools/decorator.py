"""@tool 装饰器 — 将函数注册为 LLM 可调用工具。"""
from __future__ import annotations
import asyncio
import inspect
from collections.abc import Callable
from typing import Any, get_type_hints

from app.shared.infra.tools.definition import ToolDefinition
from app.shared.infra.tools.registry import get_tool_registry

_TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


def _build_schema(func: Callable) -> dict:
    sig, hints = inspect.signature(func), get_type_hints(func)
    props: dict[str, Any] = {}
    required: list[str] = []
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        tp = hints.get(name, str)
        props[name] = {"type": _TYPE_MAP.get(tp, "string"), "description": f"参数 {name}"}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    return {"type": "object", "properties": props, "required": required}


def tool(name: str, description: str) -> Callable:
    """装饰器：将函数注册为 LLM 可调用的工具。

    用法::

        @tool("search", "搜索知识库")
        async def search(query: str, top_k: int = 5) -> str: ...
    """
    def decorator(func: Callable) -> Callable:
        td = ToolDefinition(
            name=name, description=description,
            parameters=_build_schema(func), handler=func,
            is_async=asyncio.iscoroutinefunction(func),
        )
        get_tool_registry().register(td)
        return func
    return decorator
