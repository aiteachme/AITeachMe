"""Execution mode selection for the interact workflow."""

from __future__ import annotations

from enum import Enum

from app.shared.infra.strategies import StrategyMode
from app.workflows.interact.chat.lib.types import RetrievedContext


class InteractExecutionMode(str, Enum):
    """Execution mode for one tutoring turn."""

    SINGLE_PASS = "single_pass"
    PLAN_EXECUTE = "plan_execute"


_PLANNING_KEYWORDS = (
    "学习计划",
    "复习计划",
    "怎么学",
    "先学什么",
    "路线",
    "规划",
    "计划",
)

_GUIDED_KEYWORDS = (
    "一步步",
    "逐步",
    "引导",
    "先不要告诉我",
    "别直接告诉我",
    "不要直接给答案",
    "自己推",
)

_ANALYSIS_KEYWORDS = (
    "帮我拆解",
    "帮我分析",
    "从哪开始",
    "怎么证明",
    "为什么会这样",
)


def select_execution_mode(
    *,
    question: str,
    selected_context: str | None,
    strategy_mode: StrategyMode,
    retrieval_results: list[RetrievedContext],
    allow_course_tools: bool = True,
) -> InteractExecutionMode:
    """Choose a bounded execution mode without another model call."""

    if selected_context and selected_context.strip():
        return InteractExecutionMode.SINGLE_PASS
    if not allow_course_tools:
        return InteractExecutionMode.SINGLE_PASS

    normalized_question = str(question or "").lower()
    retrieval_count = len(retrieval_results or [])

    if strategy_mode in {StrategyMode.PLANNING, StrategyMode.SOCRATIC}:
        return InteractExecutionMode.PLAN_EXECUTE
    if _contains_any(normalized_question, _PLANNING_KEYWORDS):
        return InteractExecutionMode.PLAN_EXECUTE
    if _contains_any(normalized_question, _GUIDED_KEYWORDS) and retrieval_count <= 1:
        return InteractExecutionMode.PLAN_EXECUTE
    if retrieval_count == 0 and _contains_any(normalized_question, _ANALYSIS_KEYWORDS):
        return InteractExecutionMode.PLAN_EXECUTE
    return InteractExecutionMode.SINGLE_PASS


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


__all__ = [
    "InteractExecutionMode",
    "select_execution_mode",
]
