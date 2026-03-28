"""兼容性 shim — 实际实现已移至 app.platform.strategies。"""
from app.platform.strategies import (  # noqa: F401
    Strategy,
    StrategyMode,
    StrategyRegistry,
    get_strategy_registry,
)
