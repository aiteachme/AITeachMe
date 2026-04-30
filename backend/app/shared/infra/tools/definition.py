"""工具定义。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDefinition:
    """一个可被 LLM 调用的工具。"""

    name: str
    description: str
    parameters: dict                # JSON Schema
    handler: Callable[..., Any]
    is_async: bool = False
    tags: list[str] = field(default_factory=list)
    source: str = "python"
    risk_level: str = "low"
    scopes: list[str] = field(default_factory=list)
    timeout_s: float | None = None
    requires_course: bool = False
    requires_approval: bool = False
    cache_policy: str = "none"
    hidden_args: list[str] = field(default_factory=list)

    def to_openai_format(self) -> dict:
        """转换为 OpenAI function calling 格式。"""
        parameters = _without_hidden_args(self.parameters, self.hidden_args)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }


def _without_hidden_args(parameters: dict, hidden_args: list[str]) -> dict:
    if not hidden_args:
        return parameters
    hidden = set(hidden_args)
    visible_parameters = dict(parameters or {})
    properties = dict(visible_parameters.get("properties") or {})
    for name in hidden:
        properties.pop(name, None)
    visible_parameters["properties"] = properties
    visible_parameters["required"] = [
        name
        for name in list(visible_parameters.get("required") or [])
        if name not in hidden
    ]
    return visible_parameters
