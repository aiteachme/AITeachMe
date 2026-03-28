"""Chat service adapters."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from uuid import uuid4

from fastapi import Request
from pydantic import TypeAdapter
from sqlmodel import Session

from app.platform.llm import acompletion_stream
from app.platform.model_router import TaskType
from app.models import ChatMessage, ChatSession
from app.repositories.chats_repo import (
    clear_messages_by_subject,
    count_messages_by_session_ids,
    create_chat_session,
    create_message_pair,
    delete_chat_session,
    get_chat_session,
    list_messages_by_subject,
    list_messages_by_turn_ids,
    list_sessions_by_subject,
    list_thread_turn_heads_by_subject,
    touch_chat_session,
)
from app.schemas.chats import (
    ChatClearData,
    ChatContextItem,
    ChatMessageItem,
    ChatSessionDeleteData,
    ChatSessionItem,
    ChatThreadTurnItem,
)
from app.schemas.common import PaginatedData, build_paginated_data
from app.services.presenters import require_id
from app.workflows.interact.runtime import stream_chat_workflow
from app.workflows.interact.support.messages import build_chat_messages
from app.workflows.interact.support.streaming import format_sse_event
from app.workflows.interact.support.strategies import select_teaching_strategy

_CHAT_CONTEXT_LIST_ADAPTER = TypeAdapter(list[ChatContextItem])


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
    return build_paginated_data(
        items=[
            _to_chat_session_item(
                item,
                message_count=counts.get(item.id, 0),
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
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
) -> AsyncGenerator[str, None]:
    resolved_session = _resolve_chat_session(
        session,
        subject=subject,
        user_id=user_id,
        session_id=session_id,
        question=question,
        source=source,
    )

    if source and source.strip():
        async for payload in _stream_direct_chat(
            request=request,
            session=session,
            subject=subject,
            user_id=user_id,
            chat_session=resolved_session,
            question=question,
            source=source,
            anchor_id=anchor_id,
            selected_context=selected_context,
            source_chunk_id=source_chunk_id,
        ):
            yield payload
        return

    async for payload in stream_chat_workflow(
        request=request,
        session=session,
        subject=subject,
        user_id=user_id,
        session_id=resolved_session.id,
        question=question,
        selected_context=selected_context,
        source_chunk_id=source_chunk_id,
    ):
        event_name, data = _parse_sse_payload(payload)
        if event_name != "done" or not isinstance(data, dict):
            yield payload
            continue

        turn_id = str(data.get("turn_id", "")).strip()
        if turn_id:
            touch_chat_session(
                session,
                subject=subject,
                user_id=user_id,
                session_id=resolved_session.id,
                title=_build_session_title(question) if _is_placeholder_title(resolved_session.title) else None,
            )

        done_payload = {
            **data,
            "session_id": resolved_session.id,
        }
        yield format_sse_event("done", done_payload)


async def _stream_direct_chat(
    *,
    request: Request,
    session: Session,
    subject: str,
    user_id: str,
    chat_session: ChatSession,
    question: str,
    source: str,
    anchor_id: str | None,
    selected_context: str | None,
    source_chunk_id: int | None,
) -> AsyncGenerator[str, None]:
    messages = build_chat_messages(
        subject=subject,
        strategy_mode=select_teaching_strategy(question, selected_context),
        retrieval_results=[],
        recent_messages=[],
        weak_points=[],
        recent_mistakes=[],
        question=question,
        selected_context=selected_context,
        source_chunk_id=source_chunk_id,
    )
    stream = acompletion_stream(messages, task_type=TaskType.CHAT)
    assistant_tokens: list[str] = []
    turn_id = str(uuid4())

    try:
        async for token in stream:
            if await request.is_disconnected():
                await stream.aclose()
                return
            assistant_tokens.append(token)
            yield format_sse_event("token", {"content": token})
    except Exception as exc:
        yield format_sse_event(
            "error",
            {"detail": str(exc), "error_code": "STREAM_ERROR"},
        )
        return

    assistant_content = "".join(assistant_tokens).strip()
    if not assistant_content:
        assistant_content = "I received the question, but no answer content was generated."

    create_message_pair(
        session,
        subject=subject,
        user_id=user_id,
        session_id=chat_session.id,
        user_content=question,
        assistant_content=assistant_content,
        contexts=None,
        turn_id=turn_id,
        source=source,
        anchor_id=anchor_id,
        selected_text=selected_context,
        source_chunk_id=source_chunk_id,
    )
    touch_chat_session(
        session,
        subject=subject,
        user_id=user_id,
        session_id=chat_session.id,
        title=_build_session_title(question) if _is_placeholder_title(chat_session.title) else None,
    )

    yield format_sse_event(
        "done",
        {
            "turn_id": turn_id,
            "session_id": chat_session.id,
            "contexts": None,
        },
    )


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
        title=_build_session_title(question),
    )


def _build_session_title(question: str) -> str:
    text = " ".join(question.strip().split())
    if not text:
        return "New Chat"
    max_len = 24
    return text[:max_len] if len(text) <= max_len else f"{text[:max_len]}..."


def _is_placeholder_title(title: str) -> bool:
    normalized = title.strip().lower()
    return normalized in {"", "new chat"}


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


def _to_chat_session_item(item: ChatSession, *, message_count: int) -> ChatSessionItem:
    return ChatSessionItem(
        id=item.id,
        title=item.title,
        source=item.source,
        message_count=message_count,
        created_at=item.created_at,
        updated_at=item.updated_at,
        last_message_at=item.last_message_at,
    )


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
