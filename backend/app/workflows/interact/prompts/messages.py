"""Prompt assembly for the interact workflow."""

from __future__ import annotations

from app.schemas.llm import ASSISTANT, ChatMessage, USER
from app.shared.infra.prompt_loader import populate_prompt
from app.shared.infra.strategies import StrategyMode
from app.shared.infra.token_budget import ContextWindowManager
from app.workflows.common import traceable_run
from app.workflows.interact.prompts.prompts import SYSTEM_PROMPT_TUTOR, get_strategy_instruction
from app.workflows.interact.support.types import (
    MistakeSummary,
    RecentMessage,
    RetrievedContext,
    WeakPointSummary,
)


@traceable_run(name="interact.build_chat_messages", run_type="prompt")
def build_chat_messages(
    *,
    subject: str,
    strategy_mode: StrategyMode,
    retrieval_results: list[RetrievedContext],
    recent_messages: list[RecentMessage],
    weak_points: list[WeakPointSummary],
    recent_mistakes: list[MistakeSummary],
    question: str,
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
    context_window: ContextWindowManager | None = None,
) -> list[ChatMessage]:
    """Build the full LLM message list for one tutoring turn."""

    manager = context_window or ContextWindowManager()
    system_prompt = populate_prompt(
        SYSTEM_PROMPT_TUTOR,
        subject=subject,
        teaching_strategy=get_strategy_instruction(strategy_mode),
        weak_points_context=_format_weak_points_context(weak_points),
        mistakes_context=_format_mistakes_context(recent_mistakes),
        selected_context=_format_selected_context(selected_context, source_chunk_id),
    )
    history_messages = manager.truncate_messages(
        messages=[
            {
                "role": ASSISTANT if item.role == "assistant" else USER,
                "content": item.content,
            }
            for item in recent_messages
        ],
        max_tokens=manager.budget.chat_history,
    )
    retrieval_chunks = [format_retrieval_context_item(result) for result in retrieval_results]
    return manager.build_context(
        system_prompt=system_prompt,
        retrieval_chunks=retrieval_chunks,
        chat_history=history_messages,
        user_query=question,
    )


def format_retrieval_context_item(result: RetrievedContext) -> str:
    """Format one retrieval record for the prompt context block."""

    relevance_label = "低相关" if result.low_relevance else "高相关"
    return (
        f"[资料] 标题：{result.title}\n"
        f"路径：{result.header_path}\n"
        f"相关性：{relevance_label}，分数：{result.score:.4f}\n"
        f"内容：{result.content}"
    )


def _format_weak_points_context(weak_points: list[WeakPointSummary]) -> str:
    if not weak_points:
        return "暂无薄弱项数据。"
    return "\n".join(
        f"- {item.knowledge_point}（掌握度：{item.mastery_text}）"
        for item in weak_points
    )


def _format_mistakes_context(mistakes: list[MistakeSummary]) -> str:
    if not mistakes:
        return "暂无近期错题。"
    return "\n\n".join(
        (
            f"题干：{item.question_stem}\n"
            f"用户答案：{item.user_answer}\n"
            f"正确答案：{item.correct_answer}\n"
            f"错因：{item.analysis}"
        )
        for item in mistakes
    )


def _format_selected_context(selected_context: str | None, source_chunk_id: int | None) -> str:
    if not selected_context:
        return "无。"
    if source_chunk_id is None:
        return selected_context
    return f"[chunk_id={source_chunk_id}]\n{selected_context}"


__all__ = [
    "build_chat_messages",
    "format_retrieval_context_item",
]
