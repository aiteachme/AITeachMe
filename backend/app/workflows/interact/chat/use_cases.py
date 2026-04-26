"""API-facing chat use cases built on top of the interact chat lane.

These helpers coordinate session CRUD, history reads, and SSE chat streaming
for HTTP routes. LangGraph internals remain in ``graph.py``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import Request
from pydantic import TypeAdapter
from sqlmodel import Session, select

from app.models import ChatMessage, ChatSession, Subject
from app.schemas.llm import SYSTEM, USER, ChatMessage as LLMChatMessage
from app.repositories.chats_repo import (
    clear_messages_by_subject,
    count_messages_by_session_ids,
    count_messages_by_session_ids_for_user,
    create_chat_session,
    delete_chat_session,
    get_chat_session,
    list_session_selection_heads_by_session_ids,
    list_session_selection_heads_by_session_ids_for_user,
    list_messages_by_subject,
    list_messages_by_turn_ids,
    list_sessions_by_subject,
    list_sessions_by_user,
    list_thread_turn_heads_by_subject,
    touch_chat_session,
)
from app.schemas.chats import (
    ChatClearData,
    ChatContextItem,
    ChatMessageItem,
    ChatSelectionContext,
    ChatSessionDeleteData,
    ChatSessionItem,
    ChatThreadTurnItem,
)
from app.schemas.common import PaginatedData, build_paginated_data
from app.utils.presenters import require_id
from app.utils.subject import GLOBAL_SUBJECT
from app.shared.infra.llm_support import acompletion
from app.shared.infra.llm_support.routing import LLMCallPurpose
from app.workflows.interact.chat.graph import stream_chat_workflow
from app.workflows.interact.chat.lib.streaming import format_sse_event

_CHAT_CONTEXT_LIST_ADAPTER = TypeAdapter(list[ChatContextItem])
_TITLE_GENERATION_TIMEOUT_S = 8.0
_TITLE_RESOLVE_TIMEOUT_S = 1.5
_TITLE_MAX_CHARS = 20


def list_chat_sessions(
    session: Session,
    *,
    subject: str,
    user_id: str,
    page: int,
    size: int,
) -> PaginatedData[ChatSessionItem]:
    items, total = list_sessions_by_subject(
        session,
        subject,
        user_id=user_id,
        limit=size,
        offset=(page - 1) * size,
    )
    counts = count_messages_by_session_ids(
        session,
        subject=subject,
        user_id=user_id,
        session_ids=[item.id for item in items],
    )
    selection_heads = list_session_selection_heads_by_session_ids(
        session,
        subject=subject,
        user_id=user_id,
        session_ids=[item.id for item in items],
    )
    subject_names = _load_subject_names(
        session,
        user_id=user_id,
        subject_ids={item.subject for item in items},
    )
    return build_paginated_data(
        items=[
            _to_chat_session_item(
                item,
                message_count=counts.get(item.id, 0),
                selection_head=selection_heads.get(item.id),
                subject_name=subject_names.get(item.subject),
            )
            for item in items
        ],
        page=page,
        size=size,
        total=total,
    )


def list_recent_chat_sessions(
    session: Session,
    *,
    user_id: str,
    page: int,
    size: int,
) -> PaginatedData[ChatSessionItem]:
    items, total = list_sessions_by_user(
        session,
        user_id=user_id,
        limit=size,
        offset=(page - 1) * size,
    )
    counts = count_messages_by_session_ids_for_user(
        session,
        user_id=user_id,
        session_ids=[item.id for item in items],
    )
    selection_heads = list_session_selection_heads_by_session_ids_for_user(
        session,
        user_id=user_id,
        session_ids=[item.id for item in items],
    )
    subject_names = _load_subject_names(
        session,
        user_id=user_id,
        subject_ids={item.subject for item in items},
    )
    return build_paginated_data(
        items=[
            _to_chat_session_item(
                item,
                message_count=counts.get(item.id, 0),
                selection_head=selection_heads.get(item.id),
                subject_name=subject_names.get(item.subject),
            )
            for item in items
        ],
        page=page,
        size=size,
        total=total,
    )


def create_session(
    session: Session,
    *,
    subject: str,
    user_id: str,
    title: str | None = None,
    source: str | None = None,
) -> ChatSessionItem:
    created = create_chat_session(
        session,
        subject=subject,
        user_id=user_id,
        source=source,
        title=(title or "New Chat").strip() or "New Chat",
    )
    return _to_chat_session_item(created, message_count=0)


def list_chat_threads(
    session: Session,
    *,
    subject: str,
    user_id: str,
    page: int,
    size: int,
    source: str | None = "quick_chat",
) -> PaginatedData[ChatThreadTurnItem]:
    turn_heads, total = list_thread_turn_heads_by_subject(
        session,
        subject,
        user_id=user_id,
        limit=size,
        offset=(page - 1) * size,
        source=source,
        require_anchor=True,
    )
    turn_ids = [item.turn_id for item in turn_heads]
    messages = list_messages_by_turn_ids(
        session,
        subject=subject,
        user_id=user_id,
        turn_ids=turn_ids,
    )
    messages_by_turn: dict[str, list[ChatMessage]] = {}
    for message in messages:
        messages_by_turn.setdefault(message.turn_id, []).append(message)

    return build_paginated_data(
        items=[
            _to_chat_thread_turn_item(
                item,
                messages=messages_by_turn.get(item.turn_id, []),
            )
            for item in turn_heads
        ],
        page=page,
        size=size,
        total=total,
    )


def delete_session(
    session: Session,
    *,
    subject: str,
    user_id: str,
    session_id: str,
) -> ChatSessionDeleteData:
    deleted_message_count = delete_chat_session(
        session,
        subject=subject,
        user_id=user_id,
        session_id=session_id,
    )
    return ChatSessionDeleteData(
        deleted=True,
        deleted_message_count=deleted_message_count,
    )


def list_chat_history(
    session: Session,
    *,
    subject: str,
    user_id: str,
    page: int,
    size: int,
    session_id: str | None = None,
) -> PaginatedData[ChatMessageItem]:
    items, total = list_messages_by_subject(
        session,
        subject,
        user_id=user_id,
        limit=size,
        offset=(page - 1) * size,
        session_id=session_id,
    )
    return build_paginated_data(
        items=[_to_chat_message_item(item) for item in items],
        page=page,
        size=size,
        total=total,
    )


def clear_chat_history(
    session: Session,
    *,
    subject: str,
    user_id: str,
    session_id: str | None = None,
) -> ChatClearData:
    deleted_count = clear_messages_by_subject(
        session,
        subject,
        user_id=user_id,
        session_id=session_id,
    )
    return ChatClearData(cleared=True, deleted_count=deleted_count)


async def chat_stream(
    request: Request,
    session: Session,
    *,
    subject: str,
    user_id: str,
    session_id: str | None,
    question: str,
    source: str | None = None,
    anchor_id: str | None = None,
    selected_text: str | None = None,
    selected_context: str | None = None,
    selection_context: ChatSelectionContext | None = None,
    source_chunk_id: int | None = None,
) -> AsyncGenerator[str, None]:
    resolved_session = _resolve_chat_session(
        session,
        subject=subject,
        user_id=user_id,
        session_id=session_id,
        question=question,
        source=_clean_optional(source),
    )
    title_task = _start_session_title_task(
        resolved_session=resolved_session,
        subject=subject,
        question=question,
        selected_text=selected_text,
    )

    try:
        async for payload in stream_chat_workflow(
            request=request,
            session=session,
            subject=subject,
            user_id=user_id,
            session_id=resolved_session.id,
            question=question,
            source=_clean_optional(source),
            anchor_id=_clean_optional(anchor_id),
            selected_text=selected_text,
            selected_context=selected_context,
            selection_context=selection_context,
            source_chunk_id=source_chunk_id,
        ):
            event_name, data = _parse_sse_payload(payload)
            if event_name != "done" or not isinstance(data, dict):
                yield payload
                continue

            turn_id = str(data.get("turn_id", "")).strip()
            session_title: str | None = None
            if turn_id:
                session_title = await _resolve_session_title_after_turn(
                    resolved_session=resolved_session,
                    question=question,
                    title_task=title_task,
                )
                touch_chat_session(
                    session,
                    subject=subject,
                    user_id=user_id,
                    session_id=resolved_session.id,
                    title=session_title,
                )

            done_payload = {
                **data,
                "session_id": resolved_session.id,
            }
            if session_title:
                done_payload["session_title"] = session_title
            yield format_sse_event("done", done_payload)
    finally:
        if title_task is not None and not title_task.done():
            title_task.cancel()


def _resolve_chat_session(
    session: Session,
    *,
    subject: str,
    user_id: str,
    session_id: str | None,
    question: str,
    source: str | None,
) -> ChatSession:
    if session_id and session_id.strip():
        existing = get_chat_session(
            session,
            subject=subject,
            user_id=user_id,
            session_id=session_id.strip(),
        )
        if existing:
            return existing

    return create_chat_session(
        session,
        subject=subject,
        user_id=user_id,
        source=source,
        title="New Chat",
    )


def _start_session_title_task(
    *,
    resolved_session: ChatSession,
    subject: str,
    question: str,
    selected_text: str | None,
) -> asyncio.Task[str] | None:
    if not _should_generate_session_title(resolved_session.title, question):
        return None
    return asyncio.create_task(
        _generate_session_title(
            subject=subject,
            question=question,
            selected_text=selected_text,
            assistant_response="",
        )
    )


async def _resolve_session_title_after_turn(
    *,
    resolved_session: ChatSession,
    question: str,
    title_task: asyncio.Task[str] | None,
) -> str | None:
    if not _should_generate_session_title(resolved_session.title, question):
        return None
    if title_task is None:
        return _build_session_title(question)
    try:
        return await asyncio.wait_for(title_task, timeout=_TITLE_RESOLVE_TIMEOUT_S)
    except Exception:
        return _build_session_title(question)


async def _generate_session_title(
    *,
    subject: str,
    question: str,
    selected_text: str | None,
    assistant_response: str,
) -> str:
    fallback = _build_session_title(question)
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
                    f"学科：{_clip_title_material(subject, 80)}",
                    f"用户问题：{_clip_title_material(question, 400)}",
                    f"划选原文：{_clip_title_material(selected_text, 400) or '无'}",
                    f"AI回答：{_clip_title_material(assistant_response, 900)}",
                    "请生成会话标题：",
                ]
            ),
        },
    ]
    try:
        raw_title = await asyncio.wait_for(
            acompletion(
                messages,
                call_purpose=LLMCallPurpose.SUMMARIZE,
                model="light",
                temperature=0.2,
                max_tokens=48,
            ),
            timeout=_TITLE_GENERATION_TIMEOUT_S,
        )
    except Exception:
        return fallback
    return _clean_generated_session_title(raw_title, fallback=fallback)


def _build_session_title(question: str) -> str:
    text = " ".join(question.strip().split())
    if not text:
        return "New Chat"
    max_len = 24
    return text[:max_len] if len(text) <= max_len else f"{text[:max_len]}..."


def _clip_title_material(value: str | None, max_chars: int) -> str:
    text = " ".join((value or "").strip().split())
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip()


def _clean_generated_session_title(raw_title: str, *, fallback: str) -> str:
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
    if len(title) > _TITLE_MAX_CHARS:
        title = title[:_TITLE_MAX_CHARS].rstrip()
    return title or fallback


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _is_placeholder_title(title: str) -> bool:
    normalized = title.strip().lower()
    return normalized in {"", "new chat", "新会话"}


def _should_generate_session_title(title: str, question: str) -> bool:
    return _is_placeholder_title(title) or title.strip() == _build_session_title(question)


def _parse_sse_payload(payload: str) -> tuple[str | None, object | None]:
    event_name: str | None = None
    data_lines: list[str] = []
    for line in payload.splitlines():
        if line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].strip())

    if not data_lines:
        return event_name, None

    raw_data = "\n".join(data_lines)
    try:
        return event_name, json.loads(raw_data)
    except json.JSONDecodeError:
        return event_name, raw_data


def _to_chat_message_item(message: ChatMessage) -> ChatMessageItem:
    return ChatMessageItem(
        id=require_id(message.id, "ChatMessage.id"),
        turn_id=message.turn_id,
        role=message.role,
        content=message.content,
        contexts=_normalize_chat_contexts(message.contexts_json),
        created_at=message.created_at,
    )


def _to_chat_session_item(
    item: ChatSession,
    *,
    message_count: int,
    selection_head: ChatMessage | None = None,
    subject_name: str | None = None,
) -> ChatSessionItem:
    return ChatSessionItem(
        id=item.id,
        title=item.title,
        subject_id=item.subject,
        subject_name=subject_name,
        source=item.source or (selection_head.source if selection_head else None),
        anchor_id=selection_head.anchor_id if selection_head else None,
        selected_text=selection_head.selected_text if selection_head else None,
        source_chunk_id=selection_head.source_chunk_id if selection_head else None,
        message_count=message_count,
        created_at=item.created_at,
        updated_at=item.updated_at,
        last_message_at=item.last_message_at,
    )


def _load_subject_names(
    session: Session,
    *,
    user_id: str,
    subject_ids: set[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    if GLOBAL_SUBJECT in subject_ids:
        result[GLOBAL_SUBJECT] = "通用"

    lookup_ids = [subject_id for subject_id in subject_ids if subject_id and subject_id != GLOBAL_SUBJECT]
    if not lookup_ids:
        return result

    stmt = select(Subject).where(
        Subject.user_id == user_id,
        Subject.slug.in_(lookup_ids),
    )
    for item in session.exec(stmt).all():
        result[item.slug] = item.name or item.slug
    return result


def _to_chat_thread_turn_item(
    item: ChatMessage,
    *,
    messages: list[ChatMessage],
) -> ChatThreadTurnItem:
    return ChatThreadTurnItem(
        turn_id=item.turn_id,
        session_id=item.session_id,
        source=item.source,
        anchor_id=item.anchor_id,
        selected_text=item.selected_text,
        source_chunk_id=item.source_chunk_id,
        created_at=item.created_at,
        messages=[_to_chat_message_item(message) for message in messages],
    )


def _normalize_chat_contexts(raw_contexts: object) -> list[ChatContextItem] | None:
    if raw_contexts is None:
        return None
    return _CHAT_CONTEXT_LIST_ADAPTER.validate_python(raw_contexts)


__all__ = [
    "chat_stream",
    "clear_chat_history",
    "create_session",
    "delete_session",
    "list_chat_history",
    "list_recent_chat_sessions",
    "list_chat_sessions",
    "list_chat_threads",
]
