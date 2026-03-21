"""策略注册表。"""
from __future__ import annotations
import structlog
from app.core.strategies.types import Strategy, StrategyMode

logger = structlog.get_logger()

class StrategyRegistry:
    def __init__(self) -> None:
        self._by_mode: dict[StrategyMode, Strategy] = {}
        self._by_name: dict[str, Strategy] = {}

    def register(self, s: Strategy) -> None:
        self._by_mode[s.mode] = s
        self._by_name[s.name] = s
        logger.info("strategy_registered", name=s.name, mode=s.mode.value)

    def get(self, mode: StrategyMode) -> Strategy | None:
        return self._by_mode.get(mode)

    def get_by_name(self, name: str) -> Strategy | None:
        return self._by_name.get(name)

    def list_all(self) -> list[Strategy]:
        return list(self._by_mode.values())

    def select(self, *, intent: str | None = None, context: dict | None = None) -> Strategy | None:
        if intent is None:
            return self._by_mode.get(StrategyMode.EXPLAIN)
        intent_lower = intent.lower()
        kw_map = {
            StrategyMode.SOCRATIC: ["为什么", "why", "怎么理解", "原理"],
            StrategyMode.REVIEW: ["错题", "复盘", "错了", "mistake"],
            StrategyMode.GUIDED: ["引导", "一步步", "step by step"],
            StrategyMode.PLANNING: ["计划", "规划", "plan", "学习路径"],
            StrategyMode.QUIZ: ["测试", "小测", "quiz", "考考"],
            StrategyMode.EXPLAIN: ["解释", "什么是", "explain", "讲讲"],
        }
        for mode, kws in kw_map.items():
            if any(kw in intent_lower for kw in kws):
                s = self._by_mode.get(mode)
                if s:
                    logger.debug("strategy_selected", mode=mode.value)
                    return s
        return self._by_mode.get(StrategyMode.EXPLAIN)

_registry: StrategyRegistry | None = None

def get_strategy_registry() -> StrategyRegistry:
    global _registry
    if _registry is None:
        _registry = StrategyRegistry()
    return _registry
