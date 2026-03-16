"""聊天提示词构建器。"""

from __future__ import annotations

from app.agents.interact.retriever import RetrievalResult
from app.core.prompt_loader import render_prompt
from app.schemas.llm import ASSISTANT, ChatMessage, SYSTEM, USER


def build_chat_messages(
    *,
    subject: str,
    retrieval_results: list[RetrievalResult],
    recent_messages: list[dict],
    weak_points: list[dict],
    recent_mistakes: list[dict],
    question: str,
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
) -> list[ChatMessage]:
    """拼装聊天消息列表。"""

    system_prompt = render_prompt(
        "interact/prompts/system_prompt.j2",
        subject=subject,
        retrieval_context=_format_retrieval_context(retrieval_results),
        weak_points_context=_format_weak_points_context(weak_points),
        mistakes_context=_format_mistakes_context(recent_mistakes),
        selected_context=_format_selected_context(selected_context, source_chunk_id),
    )
    messages: list[ChatMessage] = [{"role": SYSTEM, "content": system_prompt}]

    for item in recent_messages:
        if item["role"] == "assistant":
            messages.append({"role": ASSISTANT, "content": item["content"]})
        else:
            messages.append({"role": USER, "content": item["content"]})

    messages.append({"role": USER, "content": question})
    return messages


def _format_retrieval_context(results: list[RetrievalResult]) -> str:
    if not results:
        return "暂无命中资料。"

    lines = []
    for index, result in enumerate(results, start=1):
        relevance = "低相关" if result.low_relevance else "高相关"
        lines.append(
            f"[资料 {index}] 相关度：{relevance}，分数：{result.score:.4f}\n"
            f"路径：{result.header_path}\n"
            f"内容：{result.content}"
        )
    return "\n\n".join(lines)


def _format_weak_points_context(weak_points: list[dict]) -> str:
    if not weak_points:
        return "暂无薄弱项数据。"
    return "\n".join(
        f"- {item['knowledge_point']}（掌握度：{item['mastery_text']}）"
        for item in weak_points
    )


def _format_mistakes_context(mistakes: list[dict]) -> str:
    if not mistakes:
        return "暂无近期错题。"
    return "\n\n".join(
        (
            f"题干：{item['question_stem']}\n"
            f"用户答案：{item['user_answer']}\n"
            f"正确答案：{item['correct_answer']}\n"
            f"错因：{item['analysis']}"
        )
        for item in mistakes
    )


def _format_selected_context(selected_context: str | None, source_chunk_id: int | None) -> str:
    if not selected_context:
        return "无。"
    if source_chunk_id is None:
        return selected_context
    return f"[chunk_id={source_chunk_id}]\n{selected_context}"
