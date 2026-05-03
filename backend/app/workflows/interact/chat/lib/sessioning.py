"""Chat session title helpers used by API use cases and workflow nodes.

This file owns small, deterministic title cleanup helpers plus the optional
LLM title generation call. It does not create or update chat sessions; nodes
and use cases own persistence.
"""

from __future__ import annotations

import asyncio

from app.schemas.llm import SYSTEM, USER, ChatMessage as LLMChatMessage
from app.shared.infra.llm_support import acompletion
from app.workflows.interact.chat.lib.model_policy import (
    InteractModelStep,
    interact_completion_kwargs_with_metadata,
)

TITLE_GENERATION_TIMEOUT_S = 8.0
TITLE_RESOLVE_TIMEOUT_S = 1.5
TITLE_MAX_CHARS = 20


def build_session_title(question: str) -> str:
    """Build a local fallback title from the user question."""

    text = " ".join(question.strip().split())
    if not text:
        return "New Chat"
    max_len = 24
    return text[:max_len] if len(text) <= max_len else f"{text[:max_len]}..."


def should_generate_session_title(title: str, question: str) -> bool:
    """Return whether the current session title is still a placeholder."""

    return _is_placeholder_title(title) or title.strip() == build_session_title(question)


async def generate_session_title(
    *,
    course_name: str,
    question: str,
    selected_text: str | None,
    assistant_response: str,
) -> str:
    """Generate and clean one short chat session title."""

    fallback = build_session_title(question)
    messages: list[LLMChatMessage] = [
        {
            "role": SYSTEM,
            "content": (
                "你是聊天应用的会话标题生成器。"
                "只输出一个简短标题，不要解释，不要引号，不要标点结尾。"
                "标题要像 ChatGPT 会话列表一样自然，优先中文，8 到 16 个字最佳。"
            ),
        },
        {
            "role": USER,
            "content": "\n".join(
                [
                    f"课程：{clip_title_material(course_name, 80)}",
                    f"用户问题：{clip_title_material(question, 400)}",
                    f"划选原文：{clip_title_material(selected_text, 400) or '无'}",
                    f"AI回答：{clip_title_material(assistant_response, 900)}",
                    "请生成会话标题：",
                ]
            ),
        },
    ]
    try:
        raw_title = await asyncio.wait_for(
            acompletion(
                messages,
                **interact_completion_kwargs_with_metadata(
                    InteractModelStep.SESSION_TITLE,
                    extra_metadata={"substep": "interact.chat.session_title"},
                ),
            ),
            timeout=TITLE_GENERATION_TIMEOUT_S,
        )
    except Exception:
        return fallback
    return clean_generated_session_title(raw_title, fallback=fallback)


def clip_title_material(value: str | None, max_chars: int) -> str:
    """Normalize and clip material used by the title prompt."""

    text = " ".join((value or "").strip().split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def clean_generated_session_title(raw_title: str, *, fallback: str) -> str:
    """Clean provider output into the short title stored on ChatSession."""

    lines = [
        line.strip(" \t-#`*_")
        for line in str(raw_title or "").replace("\r", "\n").splitlines()
        if line.strip()
    ]
    title = lines[0] if lines else ""
    for prefix in ("会话标题：", "会话标题:", "标题：", "标题:"):
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
    title = " ".join(title.strip(" \t\"'“”‘’`*_").split())
    title = title.rstrip("。.!！?？；;，,、")
    if len(title) > TITLE_MAX_CHARS:
        title = title[:TITLE_MAX_CHARS].rstrip()
    return title or fallback


def _is_placeholder_title(title: str) -> bool:
    normalized = title.strip().lower()
    return normalized in {"", "new chat", "新会话"}


__all__ = [
    "TITLE_GENERATION_TIMEOUT_S",
    "TITLE_RESOLVE_TIMEOUT_S",
    "build_session_title",
    "clean_generated_session_title",
    "clip_title_material",
    "generate_session_title",
    "should_generate_session_title",
]
