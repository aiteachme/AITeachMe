"""教学函数注册 — 教学策略级操作。

与 @tool（原子操作）不同，Teaching Function 是**教学策略级别**的操作，
包括：解释概念、追问检查理解、生成练习题、总结要点等。

参考 OpenMAIC 的 ``Agenda → Function → Action`` 模式。

对外使用::

    from app.core.teaching import teaching_function, run_teaching_function
    from app.core.teaching import list_teaching_functions

    @teaching_function("explain", "对概念进行详细解释")
    async def explain(concept: str, style: str = "类比") -> str:
        ...

    result = await run_teaching_function("explain", concept="特征值")
    all_funcs = list_teaching_functions()
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class TeachingFunctionDef:
    """教学函数定义。"""

    name: str
    description: str
    handler: Callable
    is_async: bool = False
    category: str = "general"   # explain | quiz | review | guide | summarize
    parameters: dict = field(default_factory=dict)


# ── 注册表 ────────────────────────────────────────────────────

_registry: dict[str, TeachingFunctionDef] = {}


def teaching_function(
    name: str,
    description: str,
    *,
    category: str = "general",
) -> Callable:
    """装饰器：将函数注册为教学函数。

    教学函数与 @tool 的区别：
    - @tool = 原子能力（搜索、计算、读写）
    - @teaching_function = 教学策略（解释、追问、出题、总结）

    Args:
        name: 函数名称。
        description: 函数描述（中文）。
        category: 分类（explain / quiz / review / guide / summarize）。

    Example::

        @teaching_function("socratic_question", "用苏格拉底追问法检验理解",
                           category="quiz")
        async def socratic_question(topic: str, depth: int = 1) -> str:
            ...
    """

    def decorator(func: Callable) -> Callable:
        # 从签名生成参数描述
        sig = inspect.signature(func)
        params = {}
        for pname, param in sig.parameters.items():
            if pname in ("self", "cls"):
                continue
            params[pname] = {
                "required": param.default is inspect.Parameter.empty,
                "default": None if param.default is inspect.Parameter.empty else param.default,
            }

        tfd = TeachingFunctionDef(
            name=name,
            description=description,
            handler=func,
            is_async=asyncio.iscoroutinefunction(func),
            category=category,
            parameters=params,
        )
        _registry[name] = tfd
        logger.info("teaching_function_registered", name=name, category=category)
        return func

    return decorator


async def run_teaching_function(name: str, **kwargs) -> str:
    """执行教学函数。

    Args:
        name: 函数名称。
        **kwargs: 参数。

    Returns:
        执行结果。

    Example::

        result = await run_teaching_function("explain", concept="贝叶斯定理")
    """

    tfd = _registry.get(name)
    if tfd is None:
        available = [n for n in _registry]
        raise ValueError(f"教学函数 `{name}` 未注册。可用：{available}")

    if tfd.is_async:
        result = await tfd.handler(**kwargs)
    else:
        result = await asyncio.to_thread(tfd.handler, **kwargs)

    return str(result)


def list_teaching_functions(category: str | None = None) -> list[dict]:
    """列出已注册的教学函数。

    Args:
        category: 可选分类过滤。

    Returns:
        教学函数列表（name, description, category, parameters）。
    """

    funcs = _registry.values()
    if category:
        funcs = [f for f in funcs if f.category == category]
    return [
        {
            "name": f.name,
            "description": f.description,
            "category": f.category,
            "parameters": f.parameters,
        }
        for f in funcs
    ]


# ── 内置教学函数 ──────────────────────────────────────────────
# 以下为示例实现，实际应接入 LLM 完成


@teaching_function("explain_concept", "用通俗易懂的方式解释一个学术概念",
                    category="explain")
async def _explain_concept(concept: str, style: str = "类比") -> str:
    """解释概念。"""
    try:
        from app.core.llm import acompletion
        return await acompletion(messages=[
            {"role": "system", "content": f"你是一位优秀的教师。请用{style}的方式，用中文通俗地解释以下概念。"},
            {"role": "user", "content": concept},
        ])
    except Exception:
        return f"[explain_concept] 待解释：{concept}（风格：{style}）"


@teaching_function("check_understanding", "通过追问检查学生是否真正理解了某个概念",
                    category="quiz")
async def _check_understanding(concept: str, depth: int = 1) -> str:
    """追问检查理解。"""
    try:
        from app.core.llm import acompletion
        return await acompletion(messages=[
            {"role": "system", "content": "你是一位苏格拉底式教师。请针对学生刚学的概念提出追问，"
                                          "检验他们是否真正理解了核心要义。不要直接揭示答案。"},
            {"role": "user", "content": f"请对概念「{concept}」进行深度{depth}的追问检查"},
        ])
    except Exception:
        return f"[check_understanding] 追问：{concept}（深度：{depth}）"


@teaching_function("generate_practice", "针对薄弱点生成练习题",
                    category="quiz")
async def _generate_practice(topic: str, difficulty: str = "中等", count: int = 3) -> str:
    """生成练习题。"""
    try:
        from app.core.llm import acompletion
        return await acompletion(messages=[
            {"role": "system", "content": f"你是出题专家。请围绕主题出{count}道{difficulty}难度的练习题，"
                                          "包含答案和解析。"},
            {"role": "user", "content": topic},
        ])
    except Exception:
        return f"[generate_practice] 主题：{topic}，难度：{difficulty}，数量：{count}"


@teaching_function("summarize_session", "对一段学习对话进行要点总结",
                    category="summarize")
async def _summarize_session(conversation: str) -> str:
    """总结学习会话。"""
    try:
        from app.core.llm import acompletion
        return await acompletion(messages=[
            {"role": "system", "content": "请总结以下学习对话的要点，列出：\n"
                                          "1. 学到的核心概念\n2. 仍需加强的地方\n3. 建议下一步"},
            {"role": "user", "content": conversation},
        ])
    except Exception:
        return f"[summarize_session] 待总结的对话长度：{len(conversation)} 字"
