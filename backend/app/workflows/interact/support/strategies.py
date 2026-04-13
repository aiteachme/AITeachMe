"""Teaching strategy selection for the interact workflow."""

from __future__ import annotations

from app.shared.infra.strategies import StrategyMode

_REVIEW_KEYWORDS = ("错因", "错题", "为什么错", "哪里错", "复盘", "订正")
_GUIDED_KEYWORDS = ("一步步", "逐步", "引导", "提示我", "别直接告诉我", "不要直接给答案")
_SOCRATIC_KEYWORDS = ("启发", "追问", "让我自己想", "不要直接告诉我", "先别给答案")
_PLANNING_KEYWORDS = ("学习计划", "复习计划", "怎么学", "先学什么", "规划", "计划", "路线")
_QUIZ_KEYWORDS = ("出题", "测验", "测试", "quiz", "小测")


def select_teaching_strategy(question: str, selected_context: str | None) -> StrategyMode:
    """Pick a lightweight tutoring strategy without another LLM call."""

    normalized_question = str(question or "").lower()
    if selected_context and selected_context.strip():
        return StrategyMode.GUIDED
    if _contains_any(normalized_question, _REVIEW_KEYWORDS):
        return StrategyMode.REVIEW
    if _contains_any(normalized_question, _QUIZ_KEYWORDS):
        return StrategyMode.QUIZ
    if _contains_any(normalized_question, _PLANNING_KEYWORDS):
        return StrategyMode.PLANNING
    if _contains_any(normalized_question, _SOCRATIC_KEYWORDS):
        return StrategyMode.SOCRATIC
    if _contains_any(normalized_question, _GUIDED_KEYWORDS):
        return StrategyMode.GUIDED
    return StrategyMode.EXPLAIN


def _contains_any(question: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in question for keyword in keywords)
