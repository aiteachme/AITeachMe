"""策略框架子模块（替代 skills/，更具泛化性）。"""
from app.core.strategies.types import StrategyMode, Strategy
from app.core.strategies.registry import StrategyRegistry, get_strategy_registry
__all__ = ["StrategyMode", "Strategy", "StrategyRegistry", "get_strategy_registry"]
