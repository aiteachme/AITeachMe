"""安全确认门 — 高风险工具调用的安全控制。

当 Agent Loop 调用高风险工具时（写文件、执行代码、网络请求），
安全门会拦截并要求确认。

对外使用::

    from app.infra.security import SecurityLevel, require_confirmation
    from app.infra.security import check_action_safety

    # 方式 1：装饰器
    @tool("execute_code", "执行代码")
    @require_confirmation(level=SecurityLevel.HIGH)
    async def execute_code(code: str) -> str: ...

    # 方式 2：手动检查
    decision = await check_action_safety("execute_code", {"code": "rm -rf /"})
    if not decision.allowed:
        raise PermissionError(decision.reason)
"""

from __future__ import annotations

import contextvars
import functools
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class SecurityLevel(str, Enum):
    """安全级别。"""

    LOW = "low"         # 无风险（搜索、查询）
    MEDIUM = "medium"   # 中等风险（写入记忆、修改配置）
    HIGH = "high"       # 高风险（执行代码、文件操作、网络请求）
    CRITICAL = "critical"  # 极高风险（需人工审批）


@dataclass
class SafetyDecision:
    """安全决策结果。"""

    allowed: bool
    level: SecurityLevel
    reason: str = ""
    requires_user_confirm: bool = False


@dataclass
class SecurityRule:
    """安全规则。"""

    tool_name: str
    level: SecurityLevel
    blocked_patterns: list[str] = field(default_factory=list)
    max_calls_per_session: int = -1    # -1 = 无限制
    requires_confirmation: bool = False


# ── 规则注册表 ────────────────────────────────────────────────

_rules: dict[str, SecurityRule] = {}
# BUG-5 FIX: 使用 ContextVar 替代全局 dict，确保每个异步请求有独立的调用计数
_call_counts_var: contextvars.ContextVar[dict[str, int]] = contextvars.ContextVar(
    "security_call_counts", default=None,  # type: ignore[arg-type]
)


def _get_call_counts() -> dict[str, int]:
    """获取当前请求上下文的调用计数字典（惰性初始化）。"""
    counts = _call_counts_var.get(None)
    if counts is None:
        counts = {}
        _call_counts_var.set(counts)
    return counts

# 内置默认规则
_DEFAULT_RULES: list[SecurityRule] = [
    SecurityRule("execute_code", SecurityLevel.HIGH,
                 blocked_patterns=["rm -rf", "os.system", "subprocess.run"],
                 requires_confirmation=True),
    SecurityRule("write_file", SecurityLevel.HIGH,
                 requires_confirmation=True),
    SecurityRule("web_search", SecurityLevel.LOW),
    SecurityRule("search_kb", SecurityLevel.LOW),
    SecurityRule("remember_info", SecurityLevel.MEDIUM),
    SecurityRule("recall_info", SecurityLevel.LOW),
]

for rule in _DEFAULT_RULES:
    _rules[rule.tool_name] = rule


def register_security_rule(rule: SecurityRule) -> None:
    """注册自定义安全规则。"""
    _rules[rule.tool_name] = rule
    logger.info("security_rule_registered",
                tool=rule.tool_name, level=rule.level)


async def check_action_safety(
    tool_name: str,
    args: dict[str, Any] | None = None,
) -> SafetyDecision:
    """检查工具调用的安全性。

    Args:
        tool_name: 工具名称。
        args: 工具参数。

    Returns:
        SafetyDecision — 是否允许执行。
    """

    rule = _rules.get(tool_name)
    if rule is None:
        return SafetyDecision(allowed=True, level=SecurityLevel.LOW)

    # 1. 检查黑名单模式
    if args and rule.blocked_patterns:
        args_str = str(args).lower()
        for pattern in rule.blocked_patterns:
            if pattern.lower() in args_str:
                return SafetyDecision(
                    allowed=False,
                    level=rule.level,
                    reason=f"参数包含被禁止的模式: {pattern}",
                )

    # 2. 检查调用频率（基于请求级上下文隔离）
    counts = _get_call_counts()
    if rule.max_calls_per_session > 0:
        count = counts.get(tool_name, 0)
        if count >= rule.max_calls_per_session:
            return SafetyDecision(
                allowed=False,
                level=rule.level,
                reason=f"本次会话已调用 {count} 次，超过限制 {rule.max_calls_per_session}",
            )

    # 3. 检查是否需要确认
    if rule.requires_confirmation:
        return SafetyDecision(
            allowed=True,
            level=rule.level,
            requires_user_confirm=True,
            reason="此操作需要用户确认",
        )

    # 记录调用次数（写入当前请求上下文）
    counts[tool_name] = counts.get(tool_name, 0) + 1

    return SafetyDecision(allowed=True, level=rule.level)


def require_confirmation(level: SecurityLevel = SecurityLevel.HIGH) -> Callable:
    """装饰器：标记工具需要安全确认。

    Args:
        level: 安全级别。

    Example::

        @tool("execute_code", "执行代码")
        @require_confirmation(level=SecurityLevel.HIGH)
        async def execute_code(code: str) -> str: ...
    """

    def decorator(func: Callable) -> Callable:
        # 注册规则
        tool_name = getattr(func, "__tool_name__", func.__name__)
        _rules[tool_name] = SecurityRule(
            tool_name=tool_name,
            level=level,
            requires_confirmation=True,
        )

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            decision = await check_action_safety(tool_name, kwargs)
            if not decision.allowed:
                return f"⚠️ 安全拦截：{decision.reason}"
            if decision.requires_user_confirm:
                logger.info("security_confirmation_required",
                            tool=tool_name, level=level)
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def reset_session_counts() -> None:
    """重置当前请求上下文的调用计数（新会话开始时调用）。"""
    _call_counts_var.set({})
