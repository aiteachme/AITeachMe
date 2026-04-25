"""Prompt assembly for the interact workflow."""

from __future__ import annotations

from langsmith import traceable

from app.schemas.chats import ChatSelectionContext
from app.schemas.llm import ASSISTANT, ChatMessage, USER
from app.shared.infra.prompt_loader import populate_prompt
from app.shared.infra.strategies import StrategyMode
from app.shared.infra.llm_support.context_window import ContextWindowManager
from app.workflows.interact.chat.prompts.prompts import SYSTEM_PROMPT_TUTOR, get_strategy_instruction
from app.workflows.interact.chat.lib.types import (
    MistakeSummary,
    RecentMessage,
    RetrievedContext,
    WeakPointSummary,
)


@traceable(name="interact.build_chat_messages", run_type="prompt")
def build_chat_messages(
    *,
    subject: str,
    strategy_mode: StrategyMode,
    retrieval_results: list[RetrievedContext],
    recent_messages: list[RecentMessage],
    weak_points: list[WeakPointSummary],
    recent_mistakes: list[MistakeSummary],
    question: str,
    source: str | None = None,
    selected_context: str | None = None,
    selection_context: ChatSelectionContext | None = None,
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
        interaction_entry=_format_interaction_entry(source),
        selected_context=_format_selected_context(selection_context, selected_context, source_chunk_id),
    )
    history_messages = [
        {
            "role": ASSISTANT if item.role == "assistant" else USER,
            "content": item.content,
        }
        for item in recent_messages
    ]
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
    unit_lines = []
    if result.knowledge_unit_id is not None:
        unit_lines.append(
            f"KnowledgeUnit：#{result.knowledge_unit_id} {result.knowledge_unit_name or result.title}"
        )
    if result.knowledge_unit_type:
        unit_lines.append(f"类型：{result.knowledge_unit_type}")
    if result.relation_path:
        unit_lines.append(f"图路径：{result.relation_path}")
    if result.mastery_score is not None:
        unit_lines.append(f"用户掌握度：{result.mastery_score:.0%}")
    if result.evidence_quote:
        unit_lines.append(f"证据摘录：{result.evidence_quote}")
    unit_context = "\n".join(unit_lines)
    if unit_context:
        unit_context = f"{unit_context}\n"
    return (
        f"[资料:{result.retrieval_source}] 标题：{result.title}\n"
        f"{unit_context}"
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


def _format_interaction_entry(source: str | None) -> str:
    normalized = (source or "").strip()
    if normalized == "quick_chat":
        return "知识文档划选提问。回答时优先解释用户划选内容，并把它放回原知识脉络中。"
    if normalized == "build_assistant":
        return "知识库构建过程触发。回答时优先解释当前构建阶段、资料处理或知识文档生成结果。"
    if normalized:
        return f"外部入口触发：{normalized}。回答时保留入口上下文，但不要虚构来源。"
    return "常规学习对话。"


def _clip_text(value: str | None, max_chars: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return f"{text[: max_chars - 1]}…"


def _format_selected_context(
    selection_context: ChatSelectionContext | None,
    selected_context: str | None,
    source_chunk_id: int | None,
) -> str:
    if selection_context is not None:
        return _format_structured_selection_context(selection_context, selected_context, source_chunk_id)
    if not selected_context:
        return "无。"
    selected = _clip_text(selected_context, 2400)
    if source_chunk_id is None:
        return selected
    return f"[chunk_id={source_chunk_id}]\n{selected}"


def _format_structured_selection_context(
    context: ChatSelectionContext,
    fallback_selected_context: str | None,
    source_chunk_id: int | None,
) -> str:
    lines: list[str] = []
    if source_chunk_id is not None:
        lines.append(f"[chunk_id={source_chunk_id}]")

    selected = _clip_text(context.selected_text or fallback_selected_context, 1200)
    if selected:
        lines.append(f"划选原文：\n{selected}")

    heading_path = " > ".join(
        part.strip()
        for part in context.heading_path
        if part and part.strip()
    )
    if heading_path:
        lines.append(f"标题路径：{_clip_text(heading_path, 300)}")
    elif context.anchor_title:
        lines.append(f"所在标题：{_clip_text(context.anchor_title, 160)}")

    before_text = _clip_text(context.before_text, 900)
    after_text = _clip_text(context.after_text, 900)
    if before_text or after_text:
        local_parts = []
        if before_text:
            local_parts.append(f"上文：{before_text}")
        if after_text:
            local_parts.append(f"下文：{after_text}")
        suffix = "（已截断）" if context.local_context_truncated else ""
        lines.append(f"局部上下文{suffix}：\n" + "\n".join(local_parts))

    section_excerpt = _clip_text(context.section_excerpt, 2600)
    if section_excerpt:
        section_title = _clip_text(context.section_title or context.anchor_title, 160)
        suffix = "（已截断）" if context.section_truncated else ""
        heading = f"上级标题内容{suffix}"
        if section_title:
            heading += f"：{section_title}"
        lines.append(f"{heading}\n{section_excerpt}")

    formatted = "\n\n".join(lines).strip()
    return _clip_text(formatted, 5200) or "无。"


__all__ = [
    "build_chat_messages",
    "format_retrieval_context_item",
]
