"""Conversation-derived profile signals for the Profile pipeline.

This module reads existing chat messages and turns them into lightweight,
explainable profile hints. It does not persist long-term memory or call an LLM.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.models import ChatMessage

_DEFAULT_LIMIT = 60

_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "guided_reasoning": (
        "为什么",
        "原理",
        "推导",
        "证明",
        "一步",
        "过程",
        "思路",
        "怎么来的",
        "why",
        "derive",
        "proof",
        "step by step",
    ),
    "practice_planning": (
        "计划",
        "复习",
        "练习",
        "刷题",
        "考试",
        "考点",
        "薄弱",
        "安排",
        "plan",
        "practice",
        "exam",
        "review",
    ),
    "concise_summary": (
        "总结",
        "概括",
        "重点",
        "速记",
        "简洁",
        "brief",
        "summary",
        "cheatsheet",
    ),
    "concept_explanation": (
        "解释",
        "讲讲",
        "是什么",
        "概念",
        "例子",
        "理解",
        "explain",
        "concept",
        "example",
    ),
}

_INTENT_LABELS = {
    "guided_reasoning": "推导和步骤讲解",
    "practice_planning": "练习与复习安排",
    "concise_summary": "重点总结",
    "concept_explanation": "概念解释",
}

_STYLE_BY_INTENT = {
    "guided_reasoning": "detailed",
    "concise_summary": "concise",
}


@dataclass(frozen=True)
class ConversationProfileSignals:
    message_count: int = 0
    selected_text_count: int = 0
    dominant_intent: str | None = None
    explanation_style: str | None = None
    notes: list[str] = field(default_factory=list)


def _classify_message(content: str) -> str | None:
    normalized = content.lower()
    scores = {
        intent: sum(1 for keyword in keywords if keyword.lower() in normalized)
        for intent, keywords in _INTENT_KEYWORDS.items()
    }
    scored = [(intent, score) for intent, score in scores.items() if score > 0]
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[0][0]


def _build_notes(
    *,
    message_count: int,
    selected_text_count: int,
    dominant_intent: str | None,
    intent_counts: Counter[str],
) -> list[str]:
    if message_count <= 0:
        return []

    notes = [f"近期对话：{message_count} 次主动提问"]
    if dominant_intent:
        notes.append(f"对话偏好：更常请求{_INTENT_LABELS.get(dominant_intent, '针对性讲解')}")
    if selected_text_count >= 2:
        notes.append(f"资料使用：{selected_text_count} 次围绕划选内容追问")
    if intent_counts.get("practice_planning", 0) >= 2:
        notes.append("学习意图：近期多次询问复习、练习或考试安排")
    return notes[:4]


def build_conversation_profile_signals(
    session: Session,
    *,
    user_id: str,
    course_id: str | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> ConversationProfileSignals:
    """Build lightweight profile hints from recent user chat messages."""

    if limit <= 0:
        return ConversationProfileSignals()

    stmt = select(ChatMessage).where(
        ChatMessage.user_id == user_id,
        ChatMessage.role == "user",
    )
    if course_id:
        stmt = stmt.where(ChatMessage.course_id == course_id)

    messages = list(
        session.exec(
            stmt.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).limit(limit)
        ).all()
    )
    if not messages:
        return ConversationProfileSignals()

    intent_counts: Counter[str] = Counter()
    for message in messages:
        intent = _classify_message(message.content or "")
        if intent:
            intent_counts[intent] += 1

    dominant_intent = None
    if intent_counts:
        dominant_intent = sorted(intent_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]

    selected_text_count = sum(1 for message in messages if str(message.selected_text or "").strip())
    return ConversationProfileSignals(
        message_count=len(messages),
        selected_text_count=selected_text_count,
        dominant_intent=dominant_intent,
        explanation_style=_STYLE_BY_INTENT.get(dominant_intent or ""),
        notes=_build_notes(
            message_count=len(messages),
            selected_text_count=selected_text_count,
            dominant_intent=dominant_intent,
            intent_counts=intent_counts,
        ),
    )
