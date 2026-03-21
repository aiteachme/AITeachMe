"""工具定义数据结构。"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict
    handler: Callable[..., Any]
    engines: list[str] = field(default_factory=list)
    is_async: bool = False

    def to_openai_format(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}
