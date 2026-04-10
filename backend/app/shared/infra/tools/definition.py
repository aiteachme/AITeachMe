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

    def to_openai_format(self) -> dict:
        """转换为 OpenAI function calling 格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
