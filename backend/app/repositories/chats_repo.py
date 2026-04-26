"""Chat message data-access layer."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlmodel import Session, func, select

from app.models import ChatMessage, ChatSession
from app.utils.time import utcnow


def create_chat_session(
    session: Session,
    *,
    subject: str,
    title: str,
    source: str | None = None,
    session_id: str | None = None,
    meta_json: Any | None = None,
    user_id: str = "local",
) -> ChatSession:
    """Create one chat session."""

    now = utcnow()
    item = ChatSession(
        id=session_id or str(uuid.uuid4()),
        subject=subject,
        user_id=user_id,
        title=title,
        source=source,
        meta_json=meta_json,
        created_at=now,
        updated_at=now,
        last_message_at=now,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def create_chat_message(
    session: Session,
    *,
    subject: str,
    session_id: str,
    role: str,
    content: str,
    turn_id: str | None = None,
    source: str | None = None,
    anchor_id: str | None = None,
    selected_text: str | None = None,
    source_chunk_id: int | None = None,
    contexts: Any | None = None,
    meta_json: Any | None = None,
    user_id: str = "local",
) -> ChatMessage:
    """Create one chat message when a workflow writes turns one side at a time."""

    item = ChatMessage(
        subject=subject,
        user_id=user_id,
        session_id=session_id,
        turn_id=turn_id or str(uuid.uuid4()),
        source=source,
        anchor_id=anchor_id,
        selected_text=selected_text,
        source_chunk_id=source_chunk_id,
        role=role,
        content=content,
        contexts_json=contexts,
        meta_json=meta_json,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def get_chat_session(
    session: Session,
    *,
    subject: str,
    session_id: str,
    user_id: str = "local",
) -> ChatSession | None:
    stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.subject == subject,
        ChatSession.user_id == user_id,
    )
    return session.exec(stmt).first()


def list_sessions_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int,
    offset: int,
    user_id: str = "local",
) -> tuple[list[ChatSession], int]:
    total = session.exec(
        select(func.count())
        .select_from(ChatSession)
        .where(ChatSession.subject == subject, ChatSession.user_id == user_id)
    ).one()
    stmt = (
        select(ChatSession)
        .where(ChatSession.subject == subject, ChatSession.user_id == user_id)
        .order_by(ChatSession.last_message_at.desc(), ChatSession.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def list_sessions_by_user(
    session: Session,
    *,
    limit: int,
    offset: int,
    user_id: str = "local",
) -> tuple[list[ChatSession], int]:
    total = session.exec(
        select(func.count())
        .select_from(ChatSession)
        .where(ChatSession.user_id == user_id)
    ).one()
    stmt = (
        select(ChatSession)
        .where(ChatSession.user_id == user_id)
        .order_by(ChatSession.last_message_at.desc(), ChatSession.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def list_session_selection_heads_by_session_ids(
    session: Session,
    *,
    subject: str,
    session_ids: list[str],
    source: str = "quick_chat",
    user_id: str = "local",
) -> dict[str, ChatMessage]:
    """Return the latest doc-selection turn head for each requested session."""

    if not session_ids:
        return {}

    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.subject == subject,
            ChatMessage.user_id == user_id,
            ChatMessage.session_id.in_(session_ids),
            ChatMessage.role == "assistant",
            ChatMessage.source == source,
            ChatMessage.anchor_id.is_not(None),
            ChatMessage.anchor_id != "",
        )
        .order_by(ChatMessage.created_at.desc())
    )
    rows = session.exec(stmt).all()
    result: dict[str, ChatMessage] = {}
    for item in rows:
        if item.session_id not in result:
            result[item.session_id] = item
    return result


def list_session_selection_heads_by_session_ids_for_user(
    session: Session,
    *,
    session_ids: list[str],
    source: str = "quick_chat",
    user_id: str = "local",
) -> dict[str, ChatMessage]:
    """Return the latest doc-selection turn head for each requested session across subjects."""

    if not session_ids:
        return {}

    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.user_id == user_id,
            ChatMessage.session_id.in_(session_ids),
            ChatMessage.role == "assistant",
            ChatMessage.source == source,
            ChatMessage.anchor_id.is_not(None),
            ChatMessage.anchor_id != "",
        )
        .order_by(ChatMessage.created_at.desc())
    )
    rows = session.exec(stmt).all()
    result: dict[str, ChatMessage] = {}
    for item in rows:
        if item.session_id not in result:
            result[item.session_id] = item
    return result


def list_thread_turn_heads_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int,
    offset: int,
    source: str | None = None,
    require_anchor: bool = False,
    user_id: str = "local",
) -> tuple[list[ChatMessage], int]:
    conditions = [
        ChatMessage.subject == subject,
        ChatMessage.user_id == user_id,
        ChatMessage.role == "assistant",
    ]
    if source is not None:
        conditions.append(ChatMessage.source == source)
    if require_anchor:
        conditions.append(ChatMessage.anchor_id.is_not(None))
        conditions.append(ChatMessage.anchor_id != "")

    total = session.exec(
        select(func.count())
        .select_from(ChatMessage)
        .where(*conditions)
    ).one()

    stmt = (
        select(ChatMessage)
        .where(*conditions)
        .order_by(ChatMessage.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def touch_chat_session(
    session: Session,
    *,
    subject: str,
    session_id: str,
    user_id: str = "local",
    title: str | None = None,
    touched_at: datetime | None = None,
) -> ChatSession | None:
    item = get_chat_session(
        session,
        subject=subject,
        session_id=session_id,
        user_id=user_id,
    )
    if not item:
        return None

    now = touched_at or utcnow()
    item.updated_at = now
    item.last_message_at = now
    if title and title.strip():
        item.title = title.strip()
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def count_messages_by_session_ids(
    session: Session,
    *,
    subject: str,
    session_ids: list[str],
    user_id: str = "local",
) -> dict[str, int]:
    if not session_ids:
        return {}

    stmt = (
        select(ChatMessage.session_id, func.count(ChatMessage.id))
        .where(
            ChatMessage.subject == subject,
            ChatMessage.user_id == user_id,
            ChatMessage.session_id.in_(session_ids),
        )
        .group_by(ChatMessage.session_id)
    )
    rows = session.exec(stmt).all()
    return {session_id: int(count) for session_id, count in rows}


def count_messages_by_session_ids_for_user(
    session: Session,
    *,
    session_ids: list[str],
    user_id: str = "local",
) -> dict[str, int]:
    if not session_ids:
        return {}

    stmt = (
        select(ChatMessage.session_id, func.count(ChatMessage.id))
        .where(
            ChatMessage.user_id == user_id,
            ChatMessage.session_id.in_(session_ids),
        )
        .group_by(ChatMessage.session_id)
    )
    rows = session.exec(stmt).all()
    return {session_id: int(count) for session_id, count in rows}


def delete_chat_session(
    session: Session,
    *,
    subject: str,
    session_id: str,
    user_id: str = "local",
) -> int:
    message_items = list(
        session.exec(
            select(ChatMessage).where(
                ChatMessage.subject == subject,
                ChatMessage.user_id == user_id,
                ChatMessage.session_id == session_id,
            )
        ).all()
    )
    deleted_message_count = len(message_items)
    for item in message_items:
        session.delete(item)

    session_item = get_chat_session(
        session,
        subject=subject,
        session_id=session_id,
        user_id=user_id,
    )
    if session_item:
        session.delete(session_item)
    session.commit()
    return deleted_message_count


def create_message_pair(
    session: Session,
    *,
    subject: str,
    session_id: str,
    user_content: str,
    assistant_content: str,
    contexts: Any | None = None,
    turn_id: str | None = None,
    source: str | None = None,
    anchor_id: str | None = None,
    selected_text: str | None = None,
    source_chunk_id: int | None = None,
    user_id: str = "local",
) -> tuple[ChatMessage, ChatMessage]:
    resolved_turn_id = turn_id or str(uuid.uuid4())
    user_message = ChatMessage(
        subject=subject,
        user_id=user_id,
        session_id=session_id,
        turn_id=resolved_turn_id,
        source=source,
        anchor_id=anchor_id,
        selected_text=selected_text,
        source_chunk_id=source_chunk_id,
        role="user",
        content=user_content,
        meta_json=None,
        contexts_json=None,
    )
    assistant_message = ChatMessage(
        subject=subject,
        user_id=user_id,
        session_id=session_id,
        turn_id=resolved_turn_id,
        source=source,
        anchor_id=anchor_id,
        selected_text=selected_text,
        source_chunk_id=source_chunk_id,
        role="assistant",
        content=assistant_content,
        meta_json=None,
        contexts_json=contexts,
    )
    session.add(user_message)
    session.add(assistant_message)
    session.commit()
    session.refresh(user_message)
    session.refresh(assistant_message)
    return user_message, assistant_message


def list_messages_by_turn_ids(
    session: Session,
    *,
    subject: str,
    turn_ids: list[str],
    user_id: str = "local",
) -> list[ChatMessage]:
    if not turn_ids:
        return []

    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.subject == subject,
            ChatMessage.user_id == user_id,
            ChatMessage.turn_id.in_(turn_ids),
        )
        .order_by(ChatMessage.created_at.asc())
    )
    return list(session.exec(stmt).all())


def get_recent_turns(
    session: Session,
    subject: str,
    *,
    n_turns: int,
    session_id: str | None = None,
    user_id: str = "local",
) -> list[ChatMessage]:
    turn_stmt = select(ChatMessage.turn_id).where(
        ChatMessage.subject == subject,
        ChatMessage.user_id == user_id,
        ChatMessage.role == "user",
    )
    if session_id:
        turn_stmt = turn_stmt.where(ChatMessage.session_id == session_id)
    turn_subquery = turn_stmt.order_by(ChatMessage.created_at.desc()).limit(n_turns).subquery()

    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.subject == subject,
            ChatMessage.user_id == user_id,
            ChatMessage.turn_id.in_(select(turn_subquery.c.turn_id)),
        )
        .order_by(ChatMessage.created_at.asc())
    )
    if session_id:
        stmt = stmt.where(ChatMessage.session_id == session_id)
    return list(session.exec(stmt).all())


def list_messages_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int,
    offset: int,
    session_id: str | None = None,
    user_id: str = "local",
) -> tuple[list[ChatMessage], int]:
    conditions = [
        ChatMessage.subject == subject,
        ChatMessage.user_id == user_id,
    ]
    if session_id:
        conditions.append(ChatMessage.session_id == session_id)

    count_stmt = select(func.count()).select_from(ChatMessage).where(*conditions)
    total = session.exec(count_stmt).one()

    stmt = (
        select(ChatMessage)
        .where(*conditions)
        .order_by(ChatMessage.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def clear_messages_by_subject(
    session: Session,
    subject: str,
    *,
    session_id: str | None = None,
    user_id: str = "local",
) -> int:
    conditions = [
        ChatMessage.subject == subject,
        ChatMessage.user_id == user_id,
    ]
    if session_id:
        conditions.append(ChatMessage.session_id == session_id)

    items = list(session.exec(select(ChatMessage).where(*conditions)).all())
    count = len(items)
    for item in items:
        session.delete(item)

    if not session_id:
        sessions = list(
            session.exec(
                select(ChatSession).where(
                    ChatSession.subject == subject,
                    ChatSession.user_id == user_id,
                )
            ).all()
        )
        for item in sessions:
            session.delete(item)

    session.commit()
    return count
