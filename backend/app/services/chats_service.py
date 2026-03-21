"""Chat service adapters."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Request
from pydantic import TypeAdapter
from sqlmodel import Session

from app.models import ChatMessage
from app.repositories.chats_repo import (
    clear_messages_by_subject,
    list_messages_by_subject,
)
from app.schemas.chats import ChatClearData, ChatContextItem, ChatMessageItem
from app.schemas.common import PaginatedData, build_paginated_data
from app.services.presenters import require_id
from app.workflows.interact.runtime import stream_chat_workflow

_CHAT_CONTEXT_LIST_ADAPTER = TypeAdapter(list[ChatContextItem])


def list_chat_history(
    session: Session,
    *,
    subject: str,
    page: int,
    size: int,
) -> PaginatedData[ChatMessageItem]:
    """Read paginated chat history."""

    items, total = list_messages_by_subject(
        session,
        subject,
        limit=size,
        offset=(page - 1) * size,
    )
    return build_paginated_data(
        items=[_to_chat_message_item(item) for item in items],
        page=page,
        size=size,
        total=total,
    )


def clear_chat_history(session: Session, *, subject: str) -> ChatClearData:
    """Clear chat history for one subject."""

    deleted_count = clear_messages_by_subject(session, subject)
    return ChatClearData(cleared=True, deleted_count=deleted_count)


async def chat_stream(
    request: Request,
    session: Session,
    *,
    subject: str,
    question: str,
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
) -> AsyncGenerator[str, None]:
    """Stream one tutoring response."""

    async for payload in stream_chat_workflow(
        request=request,
        session=session,
        subject=subject,
        question=question,
        selected_context=selected_context,
        source_chunk_id=source_chunk_id,
    ):
        yield payload


def _to_chat_message_item(message: ChatMessage) -> ChatMessageItem:
    return ChatMessageItem(
        id=require_id(message.id, "ChatMessage.id"),
        turn_id=message.turn_id,
        role=message.role,
        content=message.content,
        contexts=_normalize_chat_contexts(message.contexts),
        created_at=message.created_at,
    )


def _normalize_chat_contexts(raw_contexts: object) -> list[ChatContextItem] | None:
    if raw_contexts is None:
        return None
    return _CHAT_CONTEXT_LIST_ADAPTER.validate_python(raw_contexts)
