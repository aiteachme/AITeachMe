"""护栏基类。"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class GuardrailResult:
    """护栏检查结果。"""
    passed: bool
    reason: str | None = None
    sanitized_content: str | None = None


class InputGuardrail(ABC):
    """输入安全检查基类。"""
    name: str = "input_guardrail"

    @abstractmethod
    async def check(self, content: str, *, context: dict | None = None) -> GuardrailResult: ...


class OutputGuardrail(ABC):
    """输出安全检查基类。"""
    name: str = "output_guardrail"

    @abstractmethod
    async def check(self, content: str, *, context: dict | None = None) -> GuardrailResult: ...
