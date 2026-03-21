"""Guardrail 基类与结果结构。"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class GuardrailResult:
    passed: bool
    reason: str | None = None
    sanitized_content: str | None = None

class InputGuardrail(ABC):
    name: str = "input_guardrail"
    @abstractmethod
    async def check(self, content: str, *, context: dict | None = None) -> GuardrailResult: ...

class OutputGuardrail(ABC):
    name: str = "output_guardrail"
    @abstractmethod
    async def check(self, content: str, *, context: dict | None = None) -> GuardrailResult: ...
