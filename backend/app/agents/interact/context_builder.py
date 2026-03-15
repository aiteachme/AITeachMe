"""
系统提示词构建 — Interact 引擎上下文组装

注入最近 N 轮对话摘要（内存中，无需额外表）、
UserProfile 薄弱点（mastery < 0.6）和 Mistake 记录到系统提示词。
处理可选的 selected_context 作为高优先级上下文。
"""

from __future__ import annotations

from sqlmodel import Session

from app.core.config import get_settings
from app.repositories.chat_repo import get_recent_turns
from app.repositories.exam_repo import list_mistakes_by_subject
from app.repositories.profile_repo import get_weak_points
from app.agents.interact.retriever import RetrievalResult
from app.schemas.llm import ChatMessage, SYSTEM, USER, ASSISTANT


_SYSTEM_PROMPT_BASE = """你是 AITeachMe 的 AI 学习助手，专注于为学生提供个性化的学科辅导。

你的职责：
- 基于学生上传的学习资料回答问题
- 使用苏格拉底式教学法，引导学生思考而非直接给出答案
- 重点关注学生的薄弱知识点，帮助其巩固理解
- 回答时引用相关资料内容，确保准确性

当前学科：{subject}
"""


def build_system_prompt(
    session: Session,
    subject: str,
    retrieval_results: list[RetrievalResult],
    *,
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
) -> list[ChatMessage]:
    """
    构建完整的系统提示词消息列表。

    Returns:
        包含 system 消息的 messages 列表（不含用户当前问题）。
    """
    settings = get_settings()
    parts: list[str] = [_SYSTEM_PROMPT_BASE.format(subject=subject)]

    # 1. 注入检索到的知识上下文
    if retrieval_results:
        parts.append(_build_retrieval_context(retrieval_results))

    # 2. 注入 selected_context（高优先级上下文）
    if selected_context:
        parts.append(_build_selected_context(selected_context, source_chunk_id))

    # 3. 注入薄弱点
    weak_points = get_weak_points(session, subject)
    if weak_points:
        parts.append(_build_weak_points_context(weak_points))

    # 4. 注入近期错题
    mistakes, _ = list_mistakes_by_subject(session, subject, limit=5)
    if mistakes:
        parts.append(_build_mistakes_context(mistakes))

    # 5. 低相关性提示
    all_low = all(r.low_relevance for r in retrieval_results) if retrieval_results else False
    if all_low and retrieval_results:
        parts.append(
            "\n⚠️ 注意：检索到的资料与用户问题相关性较低，该问题可能超出已上传资料范围。"
            "请在回复中提示用户这一点，并尽力基于已有资料回答。"
        )

    system_content = "\n".join(parts)
    messages: list[ChatMessage] = [ChatMessage(role=SYSTEM, content=system_content)]

    # 6. 注入最近对话历史
    recent_messages = get_recent_turns(
        session, subject, n_turns=settings.chat_history_turns
    )
    for msg in recent_messages:
        messages.append(ChatMessage(role=msg.role, content=msg.content))

    return messages


def _build_retrieval_context(results: list[RetrievalResult]) -> str:
    """将检索结果格式化为上下文文本。"""
    lines = ["\n## 相关学习资料"]
    for i, r in enumerate(results, 1):
        relevance = "⚠️低相关" if r.low_relevance else "✓相关"
        lines.append(
            f"\n### 资料 {i}（{relevance}，路径：{r.header_path}）\n{r.content}"
        )
    return "\n".join(lines)


def _build_selected_context(
    selected_context: str, source_chunk_id: int | None
) -> str:
    """格式化用户划词选中的上下文。"""
    header = "\n## 用户选中的重点内容（高优先级）"
    if source_chunk_id:
        header += f"（来源 chunk_id: {source_chunk_id}）"
    return f"{header}\n{selected_context}"


def _build_weak_points_context(weak_points: list) -> str:
    """格式化薄弱知识点列表。"""
    lines = ["\n## 学生薄弱知识点（请重点关注）"]
    for wp in weak_points[:10]:  # 最多展示 10 个
        mastery_pct = f"{wp.mastery * 100:.0f}%" if wp.mastery is not None else "未测试"
        lines.append(f"- {wp.knowledge_point}（掌握度：{mastery_pct}）")
    return "\n".join(lines)


def _build_mistakes_context(mistakes: list[dict]) -> str:
    """格式化近期错题记录。"""
    lines = ["\n## 学生近期错题（供参考）"]
    for m in mistakes:
        lines.append(
            f"- 题目：{m['question_stem']}\n"
            f"  学生答案：{m['user_answer']}｜正确答案：{m['correct_answer']}\n"
            f"  错因：{m['analysis']}"
        )
    return "\n".join(lines)
