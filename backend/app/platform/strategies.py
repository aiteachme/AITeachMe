"""策略编排框架。

将推理策略、工具、护栏组合成可选择的策略模式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import structlog

from app.platform.reasoning import ReasoningStrategy

logger = structlog.get_logger()


class StrategyMode(str, Enum):
    """策略模式（可用于教学、对话、评估等场景）。"""

    EXPLAIN = "explain"
    SOCRATIC = "socratic"
    REVIEW = "review"
    GUIDED = "guided"
    PLANNING = "planning"
    QUIZ = "quiz"


@dataclass
class Strategy:
    """一个可组合的策略。"""

    name: str
    mode: StrategyMode
    system_prompt_template: str
    reasoning_strategy: ReasoningStrategy = ReasoningStrategy.DIRECT
    tools: list[str] = field(default_factory=list)
    guardrails: list[str] = field(default_factory=list)
    description: str = ""


class StrategyRegistry:
    """策略注册表。"""

    def __init__(self) -> None:
        self._by_mode: dict[StrategyMode, Strategy] = {}

    def register(self, s: Strategy) -> None:
        self._by_mode[s.mode] = s
        logger.info("strategy_registered", name=s.name, mode=s.mode.value)

    def get(self, mode: StrategyMode) -> Strategy | None:
        return self._by_mode.get(mode)

    def list_all(self) -> list[Strategy]:
        return list(self._by_mode.values())

    def select(self, *, intent: str | None = None) -> Strategy | None:
        """根据意图自动选择策略。"""
        if not intent:
            return self._by_mode.get(StrategyMode.EXPLAIN)
        kw_map = {
            StrategyMode.SOCRATIC: ["为什么", "why", "原理"],
            StrategyMode.REVIEW: ["错题", "复盘", "错了"],
            StrategyMode.GUIDED: ["引导", "一步步", "step by step"],
            StrategyMode.PLANNING: ["计划", "规划", "plan"],
            StrategyMode.QUIZ: ["测试", "小测", "quiz"],
            StrategyMode.EXPLAIN: ["解释", "什么是", "explain"],
        }
        il = intent.lower()
        for mode, kws in kw_map.items():
            if any(kw in il for kw in kws):
                return self._by_mode.get(mode)
        return self._by_mode.get(StrategyMode.EXPLAIN)


_registry: StrategyRegistry | None = None


def get_strategy_registry() -> StrategyRegistry:
    global _registry
    if _registry is None:
        _registry = StrategyRegistry()
    return _registry
