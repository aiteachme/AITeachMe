"""工具定义。"""
from __future__ import annotations
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any


@dataclass
class ToolDefinition:
    """一个可被 LLM 调用的工具。"""

    name: str
    description: str
    parameters: dict                # JSON Schema
    handler: Callable[..., Any]
    is_async: bool = False

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
