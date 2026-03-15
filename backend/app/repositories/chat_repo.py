"""
ChatMessage CRUD — 对话记录数据访问
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlmodel import Session, select, func

from app.repositories.models import ChatMessage


def create_message_pair(
    session: Session,
    *,
    subject: str,
    user_content: str,
    assistant_content: str,
    contexts: Any | None = None,
    user_id: str = "local",
) -> tuple[ChatMessage, ChatMessage]:
    """
    创建一对对话消息（用户 + 助手），共享同一 turn_id（UUID）。
    contexts 仅写入 assistant 消息。
    """
    turn_id = str(uuid.uuid4())

    user_msg = ChatMessage(
        subject=subject,
        user_id=user_id,
        turn_id=turn_id,
        role="user",
        content=user_content,
    )
    assistant_msg = ChatMessage(
        subject=subject,
        user_id=user_id,
        turn_id=turn_id,
        role="assistant",
        content=assistant_content,
        contexts=contexts,
    )

    session.add(user_msg)
    session.add(assistant_msg)
    session.commit()
    session.refresh(user_msg)
    session.refresh(assistant_msg)
    return user_msg, assistant_msg


def get_recent_turns(
    session: Session,
    subject: str,
    *,
    n_turns: int = 10,
    user_id: str = "local",
) -> list[ChatMessage]:
    """
    按学科获取最近 N 轮对话（按 user 发起的问题计数）。
    返回这些 turn 的所有消息，按 created_at 升序排列。
    """
    # 先获取最近 N 个不同的 turn_id
    turn_subq = (
        select(ChatMessage.turn_id)
        .where(
            ChatMessage.subject == subject,
            ChatMessage.user_id == user_id,
            ChatMessage.role == "user",
        )
        .order_by(ChatMessage.created_at.desc())  # type: ignore[union-attr]
        .limit(n_turns)
    ).subquery()

    # 获取这些 turn 的所有消息
    stmt = (
        select(ChatMessage)
        .where(
            ChatMessage.subject == subject,
            ChatMessage.user_id == user_id,
            ChatMessage.turn_id.in_(select(turn_subq.c.turn_id)),  # type: ignore[union-attr]
        )
        .order_by(ChatMessage.created_at.asc())  # type: ignore[union-attr]
    )
    return list(session.exec(stmt).all())


def list_messages_by_subject(
    session: Session,
    subject: str,
    *,
    limit: int = 100,
    offset: int = 0,
    user_id: str = "local",
) -> tuple[list[ChatMessage], int]:
    """按学科分页列表对话记录，返回 (items, total)。"""
    count_stmt = (
        select(func.count())
        .select_from(ChatMessage)
        .where(ChatMessage.subject == subject, ChatMessage.user_id == user_id)
    )
    total = session.exec(count_stmt).one()

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.subject == subject, ChatMessage.user_id == user_id)
        .order_by(ChatMessage.created_at.desc())  # type: ignore[union-attr]
        .offset(offset)
        .limit(limit)
    )
    items = list(session.exec(stmt).all())
    return items, total
