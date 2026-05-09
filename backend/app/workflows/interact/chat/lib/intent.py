"""Lightweight intent helpers for ordinary vs. study chat turns."""

from __future__ import annotations

from enum import Enum
from typing import Any

from app.utils.course import is_global_course


_CONTEXTUAL_SOURCES = frozenset({"exam_question", "build_assistant"})
_BUILD_SOURCES = frozenset({"build_assistant", "build_planner"})

_LEARNING_INTENT_KEYWORDS = (
    "学习",
    "想学",
    "学一下",
    "学学",
    "教我",
    "复习",
    "课程",
    "这门课",
    "课程",
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
_WEB_RESEARCH_KEYWORDS = (
    "最新",
    "查询",
    "搜索",
    "搜一下",
    "查一下",
    "联网",
    "政策",
    "新闻",
    "进展",
    "最近",
    "今年",
    "今天",
    "当前",
    "目前",
    "latest",
    "recent",
    "search",
    "look up",
)


class ChatScene(str, Enum):
    """Product-level scene sent by the client for prompt/tool routing."""

    GLOBAL_ASSISTANT = "global_assistant"
    COURSE_CHAT = "course_chat"
    DOCUMENT_SELECTION = "document_selection"
    EXAM_QUESTION = "exam_question"
    BUILD_ASSISTANT = "build_assistant"
    HOME_INTAKE = "home_intake"
    WEB_RESEARCH = "web_research"


class ChatPromptScene(str, Enum):
    """Prompt template scene for one chat turn."""

    GENERAL = "general"
    GLOBAL_ASSISTANT = "global_assistant"
    WEB_RESEARCH = "web_research"
    COURSE_LEARNING = "course_learning"
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


def should_use_course_grounding(
    *,
    question: str,
    scene: str | None = None,
    source: str | None = None,
    has_primary_context: bool,
) -> bool:
    """Decide whether course materials should be active evidence this turn."""

    explicit_scene = parse_chat_scene(scene)
    if explicit_scene in {ChatScene.GLOBAL_ASSISTANT, ChatScene.HOME_INTAKE, ChatScene.WEB_RESEARCH}:
        return False
    if explicit_scene in {
        ChatScene.COURSE_CHAT,
        ChatScene.DOCUMENT_SELECTION,
        ChatScene.EXAM_QUESTION,
        ChatScene.BUILD_ASSISTANT,
    }:
        return True

    if (source or "").strip() == "home_intake":
        return False
    if (source or "").strip() == "course_chat":
        return True
    if (source or "").strip() in {"global_assistant", "web_research"}:
        return False
    if has_primary_context:
        return True
    if (source or "").strip() in _CONTEXTUAL_SOURCES:
        return True
    return has_explicit_learning_intent(question)


def resolve_prompt_scene(
    *,
    question: str,
    scene: str | None = None,
    source: str | None = None,
    course_id: str | None = None,
    has_primary_context: bool,
) -> ChatPromptScene:
    """Resolve the dedicated prompt template scene for one turn."""

    explicit_scene = parse_chat_scene(scene)
    if explicit_scene == ChatScene.DOCUMENT_SELECTION:
        return ChatPromptScene.DOCUMENT_SELECTION
    if explicit_scene == ChatScene.EXAM_QUESTION:
        return ChatPromptScene.EXAM_QUESTION
    if explicit_scene == ChatScene.BUILD_ASSISTANT:
        return ChatPromptScene.BUILD_ASSISTANT
    if explicit_scene == ChatScene.COURSE_CHAT:
        return ChatPromptScene.COURSE_LEARNING
    if explicit_scene == ChatScene.WEB_RESEARCH:
        return ChatPromptScene.WEB_RESEARCH
    if explicit_scene in {ChatScene.GLOBAL_ASSISTANT, ChatScene.HOME_INTAKE}:
        return ChatPromptScene.GLOBAL_ASSISTANT

    normalized_source = (source or "").strip()
    if normalized_source == "exam_question":
        return ChatPromptScene.EXAM_QUESTION
    if normalized_source in _BUILD_SOURCES:
        return ChatPromptScene.BUILD_ASSISTANT
    if normalized_source == "web_research":
        return ChatPromptScene.WEB_RESEARCH
    if normalized_source == "global_assistant":
        return ChatPromptScene.GLOBAL_ASSISTANT
    if normalized_source == "course_chat":
        return ChatPromptScene.COURSE_LEARNING
    if normalized_source == "quick_chat" and has_primary_context:
        return ChatPromptScene.DOCUMENT_SELECTION
    if is_global_course(course_id) and has_external_research_intent(question):
        return ChatPromptScene.WEB_RESEARCH
    if is_global_course(course_id):
        return ChatPromptScene.GLOBAL_ASSISTANT
    if should_use_course_grounding(
        question=question,
        scene=scene,
        source=source,
        has_primary_context=has_primary_context,
    ):
        return ChatPromptScene.COURSE_LEARNING
    return ChatPromptScene.GENERAL


def parse_chat_scene(value: str | None) -> ChatScene | None:
    """Parse a client-provided scene, returning ``None`` for legacy callers."""

    normalized = (value or "").strip()
    if not normalized:
        return None
    try:
        return ChatScene(normalized)
    except ValueError:
        return None


def has_external_research_intent(question: str) -> bool:
    """Return whether the user is asking for current or external information."""

    normalized = _normalize_text(question)
    if not normalized:
        return False
    return any(keyword.casefold() in normalized for keyword in _WEB_RESEARCH_KEYWORDS)


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").casefold().split())


__all__ = [
    "ChatScene",
    "ChatPromptScene",
    "has_external_research_intent",
    "has_entry_context",
    "has_explicit_learning_intent",
    "parse_chat_scene",
    "resolve_prompt_scene",
    "should_use_course_grounding",
]
