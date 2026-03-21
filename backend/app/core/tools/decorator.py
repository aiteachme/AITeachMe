"""@tool 装饰器。"""
from __future__ import annotations
import asyncio, inspect
from typing import Any, Callable, get_type_hints
from app.core.tools.definition import ToolDefinition
from app.core.tools.registry import get_tool_registry

def _type_to_schema(tp: Any) -> dict:
    mapping = {str: {"type": "string"}, int: {"type": "integer"}, float: {"type": "number"}, bool: {"type": "boolean"}, list: {"type": "array"}, dict: {"type": "object"}}
    origin = getattr(tp, "__origin__", None)
    if origin is list:
        args = getattr(tp, "__args__", ())
        return {"type": "array", "items": _type_to_schema(args[0]) if args else {}}
    return mapping.get(tp, {"type": "string"})

def _build_schema(func: Callable) -> dict:
    sig, hints = inspect.signature(func), get_type_hints(func)
    props, required = {}, []
    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        props[name] = {**_type_to_schema(hints.get(name, str)), "description": f"参数 {name}"}
        if param.default is inspect.Parameter.empty:
            required.append(name)
        else:
            props[name]["default"] = param.default
    return {"type": "object", "properties": props, "required": required}

def tool(name: str, description: str, *, engines: list[str] | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        td = ToolDefinition(name=name, description=description, parameters=_build_schema(func),
                            handler=func, engines=engines or [], is_async=asyncio.iscoroutinefunction(func))
        get_tool_registry().register(td)
        return func
    return decorator
