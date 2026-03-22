"""Chat service adapters."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

from fastapi import Request
from pydantic import TypeAdapter
from sqlmodel import Session

from app.core.llm import acompletion_stream
from app.core.model_router import TaskType
from app.models import ChatMessage
from app.repositories.chats_repo import (
    clear_messages_by_subject,
    list_messages_by_subject,
)
from app.schemas.chats import ChatClearData, ChatContextItem, ChatMessageItem
from app.schemas.common import PaginatedData, build_paginated_data
from app.services.presenters import require_id
from app.workflows.interact.runtime import stream_chat_workflow
from app.workflows.interact.support.messages import build_chat_messages
from app.workflows.interact.support.streaming import format_sse_event
from app.workflows.interact.support.strategies import select_teaching_strategy

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
    source: str | None = None,
    selected_context: str | None = None,
    source_chunk_id: int | None = None,
) -> AsyncGenerator[str, None]:
    """Stream one tutoring response."""

    if source and source.strip():
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
        try:
            async for token in stream:
                if await request.is_disconnected():
                    await stream.aclose()
                    return
                yield format_sse_event("token", {"content": token})
        except Exception as exc:
            yield format_sse_event(
                "error",
                {"detail": str(exc), "error_code": "STREAM_ERROR"},
            )
            return

        yield format_sse_event(
            "done",
            {
                "turn_id": str(uuid4()),
                "contexts": None,
            },
        )
        return

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
