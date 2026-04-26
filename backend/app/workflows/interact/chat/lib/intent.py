"""Lightweight intent helpers for ordinary vs. study chat turns."""

from __future__ import annotations

from enum import Enum
from typing import Any


_CONTEXTUAL_SOURCES = frozenset({"exam_question", "build_assistant"})

_LEARNING_INTENT_KEYWORDS = (
    "学习",
    "想学",
    "学一下",
    "学学",
    "教我",
    "复习",
    "课程",
    "这门课",
    "学科",
    "知识",
    "知识点",
    "章节",
    "本章",
    "这章",
    "本节",
    "这节",
    "文档",
    "资料",
    "解释",
    "讲讲",
    "讲一下",
    "是什么意思",
    "什么意思",
    "含义",
    "怎么理解",
    "怎么用",
    "用法",
    "例子",
    "举例",
    "题目",
    "做题",
    "考试",
    "作业",
    "答案",
    "错题",
    "错因",
    "练习",
    "测试",
    "测验",
    "出题",
    "小测",
    "学习计划",
    "复习计划",
    "学习路线",
    "背诵",
    "记忆",
    "掌握",
    "公式",
    "定理",
    "概念",
    "study",
    "review",
    "explain",
    "homework",
    "quiz",
    "test",
)


class ChatPromptScene(str, Enum):
    """Prompt template scene for one chat turn."""

    GENERAL = "general"
    SUBJECT_LEARNING = "subject_learning"
    DOCUMENT_SELECTION = "document_selection"
    EXAM_QUESTION = "exam_question"
    BUILD_ASSISTANT = "build_assistant"


def has_entry_context(
    *,
    selected_context: str | None,
    selection_context: Any | None,
) -> bool:
    """Return whether the turn has explicit user-selected or entry context."""

    if selected_context and selected_context.strip():
        return True
    if selection_context is None:
        return False

    text_fields = (
        "selected_text",
        "section_excerpt",
        "before_text",
        "after_text",
        "anchor_title",
        "section_title",
    )
    for field in text_fields:
        if str(getattr(selection_context, field, "") or "").strip():
            return True

    heading_path = getattr(selection_context, "heading_path", None)
    return any(str(item or "").strip() for item in (heading_path or []))


def has_explicit_learning_intent(question: str) -> bool:
    """Return whether the user explicitly asks for study/course help."""

    normalized = _normalize_text(question)
    if not normalized:
        return False
    return any(keyword.casefold() in normalized for keyword in _LEARNING_INTENT_KEYWORDS)


def should_use_subject_grounding(
    *,
    question: str,
    source: str | None,
    has_primary_context: bool,
) -> bool:
    """Decide whether subject materials should be active evidence this turn."""

    if has_primary_context:
        return True
    if (source or "").strip() in _CONTEXTUAL_SOURCES:
        return True
    return has_explicit_learning_intent(question)


def resolve_prompt_scene(
    *,
    question: str,
    source: str | None,
    has_primary_context: bool,
) -> ChatPromptScene:
    """Resolve the dedicated prompt template scene for one turn."""

    normalized_source = (source or "").strip()
    if normalized_source == "exam_question":
        return ChatPromptScene.EXAM_QUESTION
    if normalized_source == "build_assistant":
        return ChatPromptScene.BUILD_ASSISTANT
    if normalized_source == "quick_chat" and has_primary_context:
        return ChatPromptScene.DOCUMENT_SELECTION
    if should_use_subject_grounding(
        question=question,
        source=source,
        has_primary_context=has_primary_context,
    ):
        return ChatPromptScene.SUBJECT_LEARNING
    return ChatPromptScene.GENERAL


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").casefold().split())


__all__ = [
    "ChatPromptScene",
    "has_entry_context",
    "has_explicit_learning_intent",
    "resolve_prompt_scene",
    "should_use_subject_grounding",
]
