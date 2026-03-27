"""Skill 定义与 @skill 装饰器。

每个 Skill 是一个 async 函数，通过 @skill 装饰器注册。
注册后自动同步到 ToolRegistry，可被 Agent Loop 调用。
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, get_type_hints

import structlog

logger = structlog.get_logger()

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


@dataclass
class SkillDefinition:
    """Skill 定义。"""

    name: str
    description: str
    parameters: dict           # JSON Schema
    handler: Callable
    is_async: bool = False
    tags: list[str] = field(default_factory=list)

    def to_tool_definition(self):
        """将 Skill 转为 ToolDefinition 并注册到工具表。"""
        from app.core.tools.definition import ToolDefinition

        return ToolDefinition(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
            handler=self.handler,
            is_async=self.is_async,
        )


# ── Skill 注册表 ──────────────────────────────────────────────


class SkillRegistry:
    """Skill 注册表（内部使用）。"""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, sd: SkillDefinition) -> None:
        self._skills[sd.name] = sd
        logger.info("skill_registered", name=sd.name, tags=sd.tags)

        # 同步注册为 Tool
        from app.core.tools.registry import get_tool_registry
        get_tool_registry().register(sd.to_tool_definition())

    def get(self, name: str) -> SkillDefinition | None:
        return self._skills.get(name)

    def list_all(self) -> list[SkillDefinition]:
        return list(self._skills.values())


_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


# ── @skill 装饰器 ─────────────────────────────────────────────


def _build_schema(func: Callable) -> dict:
    """从函数签名自动生成 JSON Schema。"""

    sig = inspect.signature(func)
    hints = get_type_hints(func)
    props: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "cls"):
            continue
        tp = hints.get(name, str)
        prop: dict[str, Any] = {
            "type": _TYPE_MAP.get(tp, "string"),
        }
        # 尝试从 docstring 或参数名生成描述
        prop["description"] = f"参数 {name}"
        props[name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {"type": "object", "properties": props, "required": required}


def skill(
    name: str,
    description: str,
    *,
    tags: list[str] | None = None,
) -> Callable:
    """装饰器：将函数注册为可被 LLM 调用的教学 Skill。

    Skill 注册后自动同步到 ToolRegistry，可被 Agent Loop 发现和调用。

    Args:
        name: Skill 名称（英文标识符）。
        description: Skill 描述（中文，会作为 LLM 的工具描述）。
        tags: 可选标签（用于分类，如 ["教学", "检索"]）。

    Example::

        @skill("find_resources", "根据学习主题搜索互联网上的免费学习资料")
        async def find_resources(topic: str, difficulty: str = "入门") -> str:
            ...
    """

    def decorator(func: Callable) -> Callable:
        sd = SkillDefinition(
            name=name,
            description=description,
            parameters=_build_schema(func),
            handler=func,
            is_async=asyncio.iscoroutinefunction(func),
            tags=tags or [],
        )
        get_skill_registry().register(sd)
        return func

    return decorator
