"""Teaching strategy selection for the interact workflow."""

from __future__ import annotations

from app.infra.strategies import StrategyMode

_REVIEW_KEYWORDS = ("错因", "错题", "为什么错", "哪里错", "复盘", "订正")


def select_teaching_strategy(question: str, selected_context: str | None) -> StrategyMode:
    """Pick a lightweight tutoring strategy without another LLM call."""

    if selected_context and selected_context.strip():
        return StrategyMode.GUIDED
    if _contains_any(question, _REVIEW_KEYWORDS):
        return StrategyMode.REVIEW
    return StrategyMode.EXPLAIN


def build_strategy_instruction(mode: StrategyMode) -> str:
    """Return a short instruction block for the selected tutoring mode."""

    instructions = {
        StrategyMode.EXPLAIN: "优先做清晰讲解，先定义概念，再结合当前资料给出直观例子。",
        StrategyMode.GUIDED: "优先做引导式教学，不要直接给最终结论，先拆解步骤并逐步提示。",
        StrategyMode.REVIEW: "优先做错因复盘，先指出误区，再结合证据解释正确思路。",
        StrategyMode.SOCRATIC: "优先用追问启发用户自己推导，不要一次性灌输答案。",
        StrategyMode.PLANNING: "优先帮用户制定后续学习顺序，强调先修关系和下一步建议。",
        StrategyMode.QUIZ: "优先用一问一练方式互动，给出简短提示并鼓励用户先作答。",
    }
    return instructions.get(mode, instructions[StrategyMode.EXPLAIN])


def _contains_any(question: str, keywords: tuple[str, ...]) -> bool:
    normalized = question.lower()
    return any(keyword in normalized for keyword in keywords)
