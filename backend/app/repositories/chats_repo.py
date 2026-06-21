"""Chat message data-access layer."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Session, func, select

from app.models import ChatMessage, ChatSession, Course
from app.utils.time import utcnow
from app.utils.course import GLOBAL_COURSE

PLANNER_CHAT_SOURCE = "build_planner"
LIBRARY_SELECTION_SOURCE = "library_selection"
LIBRARY_SELECTION_SOURCE_PREFIX = f"{LIBRARY_SELECTION_SOURCE}:"


def _library_file_id_from_source(source: str | None) -> str | None:
    normalized = (source or "").strip()
    if not normalized.startswith(LIBRARY_SELECTION_SOURCE_PREFIX):
        return None
    file_id = normalized[len(LIBRARY_SELECTION_SOURCE_PREFIX):].strip()
    return file_id or None


def _is_library_selection_source(source: str | None) -> bool:
    normalized = (source or "").strip()
    return normalized == LIBRARY_SELECTION_SOURCE or normalized.startswith(LIBRARY_SELECTION_SOURCE_PREFIX)


def _library_selection_source_condition() -> sa.ColumnElement[bool]:
    return sa.or_(
        ChatMessage.source == LIBRARY_SELECTION_SOURCE,
        ChatMessage.source.like(f"{LIBRARY_SELECTION_SOURCE_PREFIX}%"),
    )


def _selection_head_condition(source: str | None) -> sa.ColumnElement[bool]:
    has_selected_text = sa.and_(
        ChatMessage.selected_text.is_not(None),
        ChatMessage.selected_text != "",
    )
    has_anchor = sa.and_(
        ChatMessage.anchor_id.is_not(None),
        ChatMessage.anchor_id != "",
    )
    if _is_library_selection_source(source):
        return has_selected_text
    if source is not None:
        return has_anchor
    return sa.or_(
        has_anchor,
        sa.and_(_library_selection_source_condition(), has_selected_text),
    )


def create_chat_session(
    session: Session,
    *,
    course_id: str,
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
        course_id=course_id,
        user_id=user_id,
        title=title,
        source=source,
        library_file_id=_library_file_id_from_source(source),
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
    course_id: str,
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
        course_id=course_id,
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
    course_id: str,
    session_id: str,
    user_id: str = "local",
) -> ChatSession | None:
    stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.course_id == course_id,
        ChatSession.user_id == user_id,
    )
    return session.exec(stmt).first()


def list_sessions_by_course(
    session: Session,
    course_id: str,
    *,
    limit: int,
    offset: int,
    source: str | None = None,
    user_id: str = "local",
) -> tuple[list[ChatSession], int]:
    visible_builder_session = _visible_singleton_build_planner_session_condition()
    conditions = [
        ChatSession.course_id == course_id,
        ChatSession.user_id == user_id,
        visible_builder_session,
    ]
    if source is not None:
        conditions.append(ChatSession.source == source)
    total = session.exec(
        select(func.count())
        .select_from(ChatSession)
        .where(*conditions)
    ).one()
    stmt = (
        select(ChatSession)
        .where(*conditions)
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
    source: str | None = None,
    user_id: str = "local",
) -> tuple[list[ChatSession], int]:
    course_exists = (
        select(Course.id)
        .where(
            Course.user_id == user_id,
            Course.id == ChatSession.course_id,
        )
        .exists()
    )
    visible_session = sa.or_(ChatSession.course_id == GLOBAL_COURSE, course_exists)
    visible_builder_session = _visible_singleton_build_planner_session_condition()
    conditions = [ChatSession.user_id == user_id, visible_session, visible_builder_session]
    if source is not None:
        conditions.append(ChatSession.source == source)
    total = session.exec(
        select(func.count())
        .select_from(ChatSession)
        .where(*conditions)
    ).one()
    stmt = (
        select(ChatSession)
        .where(*conditions)
        .order_by(ChatSession.last_message_at.desc(), ChatSession.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def _visible_singleton_build_planner_session_condition() -> sa.ColumnElement[bool]:
    """Only expose the latest build planner session per course in chat lists."""

    latest_planner = sa.orm.aliased(ChatSession)
    latest_planner_session_id = (
        select(latest_planner.id)
        .where(
            latest_planner.course_id == ChatSession.course_id,
            latest_planner.user_id == ChatSession.user_id,
            latest_planner.source == PLANNER_CHAT_SOURCE,
        )
        .order_by(
            latest_planner.last_message_at.desc(),
            latest_planner.updated_at.desc(),
            latest_planner.created_at.desc(),
            latest_planner.id.desc(),
        )
        .limit(1)
        .scalar_subquery()
    )
    return sa.or_(
        ChatSession.source.is_(None),
        ChatSession.source != PLANNER_CHAT_SOURCE,
        ChatSession.id == latest_planner_session_id,
    )


def list_session_selection_heads_by_session_ids(
    session: Session,
    *,
    course_id: str,
    session_ids: list[str],
    source: str | None = None,
    user_id: str = "local",
) -> dict[str, ChatMessage]:
    """Return the latest anchored turn head for each requested session."""

    if not session_ids:
        return {}

    conditions = [
        ChatMessage.course_id == course_id,
        ChatMessage.user_id == user_id,
        ChatMessage.session_id.in_(session_ids),
        ChatMessage.role == "assistant",
    ]
    conditions.append(_selection_head_condition(source))
    if source is not None:
        conditions.append(ChatMessage.source == source)

    stmt = (
        select(ChatMessage)
        .where(*conditions)
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
    source: str | None = None,
    user_id: str = "local",
) -> dict[str, ChatMessage]:
    """Return the latest anchored turn head for each requested session across courses."""

    if not session_ids:
        return {}

    conditions = [
        ChatMessage.user_id == user_id,
        ChatMessage.session_id.in_(session_ids),
        ChatMessage.role == "assistant",
    ]
    conditions.append(_selection_head_condition(source))
    if source is not None:
        conditions.append(ChatMessage.source == source)

    stmt = (
        select(ChatMessage)
        .where(*conditions)
        .order_by(ChatMessage.created_at.desc())
    )
    rows = session.exec(stmt).all()
    result: dict[str, ChatMessage] = {}
    for item in rows:
        if item.session_id not in result:
            result[item.session_id] = item
    return result


def list_thread_turn_heads_by_course(
    session: Session,
    course_id: str,
    *,
    limit: int,
    offset: int,
    source: str | None = None,
    require_anchor: bool = False,
    user_id: str = "local",
) -> tuple[list[ChatMessage], int]:
    conditions = [
        ChatMessage.course_id == course_id,
        ChatMessage.user_id == user_id,
        ChatMessage.role == "assistant",
    ]
    if source is not None:
        conditions.append(ChatMessage.source == source)
    if require_anchor:
        conditions.append(_selection_head_condition(source))

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
    course_id: str,
    session_id: str,
    user_id: str = "local",
    title: str | None = None,
    touched_at: datetime | None = None,
) -> ChatSession | None:
    item = get_chat_session(
        session,
        course_id=course_id,
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
    course_id: str,
    session_ids: list[str],
    user_id: str = "local",
) -> dict[str, int]:
    if not session_ids:
        return {}

    stmt = (
        select(ChatMessage.session_id, func.count(ChatMessage.id))
        .where(
            ChatMessage.course_id == course_id,
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


def _count_chat_messages(session: Session, *conditions: Any) -> int:
    return int(
        session.exec(
            select(func.count())
            .select_from(ChatMessage)
            .where(*conditions)
        ).one()
        or 0
    )


def delete_chat_session(
    session: Session,
    *,
    course_id: str,
    session_id: str,
    user_id: str = "local",
) -> int:
    message_conditions = [
        ChatMessage.course_id == course_id,
        ChatMessage.user_id == user_id,
        ChatMessage.session_id == session_id,
    ]
    deleted_message_count = _count_chat_messages(session, *message_conditions)

    session.exec(
        sa.delete(ChatMessage)
        .where(*message_conditions)
        .execution_options(synchronize_session=False)
    )
    session.exec(
        sa.delete(ChatSession)
        .where(
            ChatSession.id == session_id,
            ChatSession.course_id == course_id,
            ChatSession.user_id == user_id,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return deleted_message_count


def create_message_pair(
    session: Session,
    *,
    course_id: str,
    session_id: str,
    user_content: str,
    assistant_content: str,
    contexts: Any | None = None,
    turn_id: str | None = None,
    source: str | None = None,
    anchor_id: str | None = None,
    selected_text: str | None = None,
    source_chunk_id: int | None = None,
    client_actions: Any | None = None,
    user_id: str = "local",
) -> tuple[ChatMessage, ChatMessage]:
    resolved_turn_id = turn_id or str(uuid.uuid4())
    assistant_meta = {"client_actions": client_actions} if client_actions else None
    user_message = ChatMessage(
        course_id=course_id,
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
        course_id=course_id,
        user_id=user_id,
        session_id=session_id,
        turn_id=resolved_turn_id,
        source=source,
        anchor_id=anchor_id,
        selected_text=selected_text,
        source_chunk_id=source_chunk_id,
        role="assistant",
        content=assistant_content,
        meta_json=assistant_meta,
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
    course_id: str,
    turn_ids: list[str],
    user_id: str = "local",
) -> list[ChatMessage]:
    if not turn_ids:
        return []

    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.course_id == course_id,
            ChatMessage.user_id == user_id,
            ChatMessage.turn_id.in_(turn_ids),
        )
        .order_by(ChatMessage.created_at.asc())
    )
    return list(session.exec(stmt).all())


def get_recent_turns(
    session: Session,
    course_id: str,
    *,
    n_turns: int,
    session_id: str | None = None,
    user_id: str = "local",
) -> list[ChatMessage]:
    turn_stmt = select(ChatMessage.turn_id).where(
        ChatMessage.course_id == course_id,
        ChatMessage.user_id == user_id,
        ChatMessage.role == "user",
    )
    if session_id:
        turn_stmt = turn_stmt.where(ChatMessage.session_id == session_id)
    turn_subquery = turn_stmt.order_by(ChatMessage.created_at.desc()).limit(n_turns).subquery()

    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.course_id == course_id,
            ChatMessage.user_id == user_id,
            ChatMessage.turn_id.in_(select(turn_subquery.c.turn_id)),
        )
        .order_by(ChatMessage.created_at.asc())
    )
    if session_id:
        stmt = stmt.where(ChatMessage.session_id == session_id)
    return list(session.exec(stmt).all())


def list_messages_by_course(
    session: Session,
    course_id: str,
    *,
    limit: int,
    offset: int,
    session_id: str | None = None,
    user_id: str = "local",
) -> tuple[list[ChatMessage], int]:
    conditions = [
        ChatMessage.course_id == course_id,
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


def clear_messages_by_course(
    session: Session,
    course_id: str,
    *,
    session_id: str | None = None,
    user_id: str = "local",
) -> int:
    conditions = [
        ChatMessage.course_id == course_id,
        ChatMessage.user_id == user_id,
    ]
    if session_id:
        conditions.append(ChatMessage.session_id == session_id)

    count = _count_chat_messages(session, *conditions)
    session.exec(
        sa.delete(ChatMessage)
        .where(*conditions)
        .execution_options(synchronize_session=False)
    )

    if not session_id:
        session.exec(
            sa.delete(ChatSession)
            .where(
                ChatSession.course_id == course_id,
                ChatSession.user_id == user_id,
            )
            .execution_options(synchronize_session=False)
        )

    session.commit()
    return count
