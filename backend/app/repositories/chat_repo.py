"""聊天记录数据访问层。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import Session, func, select

from app.models import ChatMessage


def create_message_pair(
    session: Session,
    *,
    subject: str,
    user_content: str,
    assistant_content: str,
    contexts: Any | None = None,
    user_id: str = "local",
) -> tuple[ChatMessage, ChatMessage]:
    """创建一轮对话消息。"""

    turn_id = str(uuid.uuid4())
    user_message = ChatMessage(
        subject=subject,
        user_id=user_id,
        turn_id=turn_id,
        role="user",
        content=user_content,
    )
    assistant_message = ChatMessage(
        subject=subject,
        user_id=user_id,
        turn_id=turn_id,
        role="assistant",
        content=assistant_content,
        contexts=contexts,
    )
    session.add(user_message)
    session.add(assistant_message)
    session.commit()
    session.refresh(user_message)
    session.refresh(assistant_message)
    return user_message, assistant_message


def get_recent_turns(
    session: Session,
    subject: str,
    *,
    n_turns: int,
    user_id: str = "local",
) -> list[ChatMessage]:
    """读取最近 N 轮对话。"""

    turn_subquery = (
        select(ChatMessage.turn_id)
        .where(
            ChatMessage.subject == subject,
            ChatMessage.user_id == user_id,
            ChatMessage.role == "user",
        )
        .order_by(ChatMessage.created_at.desc())  # type: ignore[union-attr]
        .limit(n_turns)
    ).subquery()

    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.subject == subject,
            ChatMessage.user_id == user_id,
            ChatMessage.turn_id.in_(select(turn_subquery.c.turn_id)),  # type: ignore[union-attr]
        )
        .order_by(ChatMessage.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def list_messages_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int,
    offset: int,
    user_id: str = "local",
) -> tuple[list[ChatMessage], int]:
    """分页查询聊天记录。"""

    total = session.exec(
        select(func.count())
        .select_from(ChatMessage)
        .where(ChatMessage.subject == subject, ChatMessage.user_id == user_id)
    ).one()
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.subject == subject, ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    return list(session.exec(stmt).all()), total


def clear_messages_by_subject(
    session: Session,
    subject: str,
    *,
    user_id: str = "local",
) -> int:
    """清空学科下的聊天记录。"""

    items = list(
        session.exec(
            select(ChatMessage).where(
                ChatMessage.subject == subject,
                ChatMessage.user_id == user_id,
            )
        ).all()
    )
    count = len(items)
    for item in items:
        session.delete(item)
    session.commit()
    return count
