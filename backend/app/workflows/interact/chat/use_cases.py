"""API-facing chat use cases built on top of the interact chat lane.

These helpers coordinate session-list CRUD, history reads, and the SSE shell
for HTTP routes. Send-time session writes live inside the LangGraph workflow.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from fastapi import Request
from pydantic import TypeAdapter
from sqlmodel import Session, select

from app.models import ChatMessage, ChatSession, Course
from app.repositories.chats_repo import (
    clear_messages_by_course,
    count_messages_by_session_ids,
    count_messages_by_session_ids_for_user,
    create_chat_session,
    delete_chat_session,
    list_session_selection_heads_by_session_ids,
    list_session_selection_heads_by_session_ids_for_user,
    list_messages_by_course,
    list_messages_by_turn_ids,
    list_sessions_by_course,
    list_sessions_by_user,
    list_thread_turn_heads_by_course,
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
from app.utils.course import GLOBAL_COURSE
from app.workflows.interact.chat.graph import stream_chat_workflow
from app.workflows.interact.chat.lib.sessioning import (
    build_session_title,
    clean_generated_session_title,
    clip_title_material,
    generate_session_title,
    should_generate_session_title,
)

_CHAT_CONTEXT_LIST_ADAPTER = TypeAdapter(list[ChatContextItem])


def list_chat_sessions(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    page: int,
    size: int,
) -> PaginatedData[ChatSessionItem]:
    items, total = list_sessions_by_course(
        session,
        course_id,
        user_id=user_id,
        limit=size,
        offset=(page - 1) * size,
    )
    counts = count_messages_by_session_ids(
        session,
        course_id=course_id,
        user_id=user_id,
        session_ids=[item.id for item in items],
    )
    selection_heads = list_session_selection_heads_by_session_ids(
        session,
        course_id=course_id,
        user_id=user_id,
        session_ids=[item.id for item in items],
    )
    course_names = _load_course_names(
        session,
        user_id=user_id,
        course_ids={item.course_id for item in items},
    )
    return build_paginated_data(
        items=[
            _to_chat_session_item(
                item,
                message_count=counts.get(item.id, 0),
                selection_head=selection_heads.get(item.id),
                course_name=course_names.get(item.course_id),
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
    course_names = _load_course_names(
        session,
        user_id=user_id,
        course_ids={item.course_id for item in items},
    )
    return build_paginated_data(
        items=[
            _to_chat_session_item(
                item,
                message_count=counts.get(item.id, 0),
                selection_head=selection_heads.get(item.id),
                course_name=course_names.get(item.course_id),
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
    course_id: str,
    user_id: str,
    title: str | None = None,
    source: str | None = None,
) -> ChatSessionItem:
    created = create_chat_session(
        session,
        course_id=course_id,
        user_id=user_id,
        source=source,
        title=(title or "New Chat").strip() or "New Chat",
    )
    return _to_chat_session_item(created, message_count=0)


def list_chat_threads(
    session: Session,
    *,
    course_id: str,
    user_id: str,
    page: int,
    size: int,
    source: str | None = "quick_chat",
) -> PaginatedData[ChatThreadTurnItem]:
    turn_heads, total = list_thread_turn_heads_by_course(
        session,
        course_id,
        user_id=user_id,
        limit=size,
        offset=(page - 1) * size,
        source=source,
        require_anchor=True,
    )
    turn_ids = [item.turn_id for item in turn_heads]
    messages = list_messages_by_turn_ids(
        session,
        course_id=course_id,
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
    course_id: str,
    user_id: str,
    session_id: str,
) -> ChatSessionDeleteData:
    deleted_message_count = delete_chat_session(
        session,
        course_id=course_id,
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
    course_id: str,
    user_id: str,
    page: int,
    size: int,
    session_id: str | None = None,
) -> PaginatedData[ChatMessageItem]:
    items, total = list_messages_by_course(
        session,
        course_id,
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
    course_id: str,
    user_id: str,
    session_id: str | None = None,
) -> ChatClearData:
    deleted_count = clear_messages_by_course(
        session,
        course_id,
        user_id=user_id,
        session_id=session_id,
    )
    return ChatClearData(cleared=True, deleted_count=deleted_count)


async def chat_stream(
    request: Request,
    session: Session | None,
    *,
    course_id: str,
    user_id: str,
    session_id: str | None,
    question: str,
    scene: str | None = None,
    source: str | None = None,
    model: str | None = None,
    anchor_id: str | None = None,
    selected_text: str | None = None,
    selected_context: str | None = None,
    selection_context: ChatSelectionContext | None = None,
    source_chunk_id: int | None = None,
    attached_file_ids: list[str] | None = None,
) -> AsyncGenerator[str, None]:
    async for payload in stream_chat_workflow(
        request=request,
        session=session,
        course_id=course_id,
        user_id=user_id,
        session_id=_clean_optional(session_id),
        question=question,
        scene=_clean_optional(scene),
        source=_clean_optional(source),
        model=_clean_optional(model),
        anchor_id=_clean_optional(anchor_id),
        selected_text=selected_text,
        selected_context=selected_context,
        selection_context=selection_context,
        source_chunk_id=source_chunk_id,
        attached_file_ids=attached_file_ids,
    ):
        yield payload


async def _generate_session_title(
    *,
    course_name: str,
    question: str,
    selected_text: str | None,
    assistant_response: str,
) -> str:
    return await generate_session_title(
        course_name=course_name,
        question=question,
        selected_text=selected_text,
        assistant_response=assistant_response,
    )


def _build_session_title(question: str) -> str:
    return build_session_title(question)


def _clip_title_material(value: str | None, max_chars: int) -> str:
    return clip_title_material(value, max_chars)


def _clean_generated_session_title(raw_title: str, *, fallback: str) -> str:
    return clean_generated_session_title(raw_title, fallback=fallback)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _is_placeholder_title(title: str) -> bool:
    return should_generate_session_title(title, "")


def _should_generate_session_title(title: str, question: str) -> bool:
    return should_generate_session_title(title, question)


def _to_chat_message_item(message: ChatMessage) -> ChatMessageItem:
    return ChatMessageItem(
        id=require_id(message.id, "ChatMessage.id"),
        turn_id=message.turn_id,
        role=message.role,
        content=message.content,
        contexts=_normalize_chat_contexts(message.contexts_json),
        client_actions=_normalize_client_actions(message.meta_json),
        created_at=message.created_at,
    )


def _normalize_client_actions(raw_meta: object) -> list[dict] | None:
    if not isinstance(raw_meta, dict):
        return None
    client_actions = raw_meta.get("client_actions")
    if not isinstance(client_actions, list):
        return None
    actions = [item for item in client_actions if isinstance(item, dict) and item.get("type")]
    return actions or None


def _to_chat_session_item(
    item: ChatSession,
    *,
    message_count: int,
    selection_head: ChatMessage | None = None,
    course_name: str | None = None,
) -> ChatSessionItem:
    return ChatSessionItem(
        id=item.id,
        title=item.title,
        course_id=item.course_id,
        course_name=course_name,
        source=item.source or (selection_head.source if selection_head else None),
        anchor_id=selection_head.anchor_id if selection_head else None,
        selected_text=selection_head.selected_text if selection_head else None,
        source_chunk_id=selection_head.source_chunk_id if selection_head else None,
        message_count=message_count,
        created_at=item.created_at,
        updated_at=item.updated_at,
        last_message_at=item.last_message_at,
    )


def _load_course_names(
    session: Session,
    *,
    user_id: str,
    course_ids: set[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    if GLOBAL_COURSE in course_ids:
        result[GLOBAL_COURSE] = "通用"

    lookup_ids = [course_id for course_id in course_ids if course_id and course_id != GLOBAL_COURSE]
    if not lookup_ids:
        return result

    stmt = select(Course).where(
        Course.user_id == user_id,
        Course.id.in_(lookup_ids),
    )
    for item in session.exec(stmt).all():
        result[item.id] = item.name or "未命名课程"
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
