"""推理策略枚举与配置。"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum

class ReasoningStrategy(str, Enum):
    DIRECT = "direct"
    COT = "cot"
    REACT = "react"
    PLAN_AND_SOLVE = "plan_and_solve"
    REFLECT = "reflect"

@dataclass
class ReasoningConfig:
    strategy: ReasoningStrategy = ReasoningStrategy.DIRECT
    max_reasoning_steps: int = 5
    show_reasoning: bool = False

@dataclass
class ReasoningResult:
    final_answer: str
    reasoning_trace: list[str] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    total_tokens: int = 0
