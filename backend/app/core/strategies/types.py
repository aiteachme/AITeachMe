"""策略类型定义。"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from app.core.reasoning.strategies import ReasoningStrategy

class StrategyMode(str, Enum):
    """策略模式枚举（可用于教学、对话、评估等任意场景）。"""
    EXPLAIN = "explain"
    SOCRATIC = "socratic"
    REVIEW = "review"
    GUIDED = "guided"
    PLANNING = "planning"
    QUIZ = "quiz"

@dataclass
class Strategy:
    """一个可组合的策略定义。"""
    name: str
    mode: StrategyMode
    system_prompt_template: str
    reasoning_strategy: ReasoningStrategy = ReasoningStrategy.DIRECT
    context_requirements: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    guardrails: list[str] = field(default_factory=list)
    description: str = ""
