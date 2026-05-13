from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine, func, select

from app.models import ChatMessage, ChatSession
from app.repositories.chats_repo import (
    clear_messages_by_course,
    create_chat_message,
    create_chat_session,
    delete_chat_session,
)


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(
        engine,
        tables=[ChatSession.__table__, ChatMessage.__table__],
    )
    return Session(engine, expire_on_commit=False)


def _count_messages(session: Session, *, course_id: str | None = None) -> int:
    stmt = select(func.count()).select_from(ChatMessage)
    if course_id is not None:
        stmt = stmt.where(ChatMessage.course_id == course_id)
    return int(session.exec(stmt).one() or 0)


def _count_sessions(session: Session, *, course_id: str | None = None) -> int:
    stmt = select(func.count()).select_from(ChatSession)
    if course_id is not None:
        stmt = stmt.where(ChatSession.course_id == course_id)
    return int(session.exec(stmt).one() or 0)


def _message_contents(session: Session, *, course_id: str) -> list[str]:
    stmt = (
        select(ChatMessage.content)
        .where(ChatMessage.course_id == course_id)
        .order_by(ChatMessage.content.asc())
    )
    return list(session.exec(stmt).all())


def test_delete_chat_session_bulk_deletes_only_target_session() -> None:
    with _session() as session:
        create_chat_session(
            session,
            course_id="course-a",
            session_id="session-a",
            title="Session A",
            user_id="user-a",
        )
        create_chat_session(
            session,
            course_id="course-a",
            session_id="session-b",
            title="Session B",
            user_id="user-a",
        )
        for index in range(3):
            create_chat_message(
                session,
                course_id="course-a",
                session_id="session-a",
                role="user",
                content=f"message {index}",
                user_id="user-a",
            )
        create_chat_message(
            session,
            course_id="course-a",
            session_id="session-b",
            role="user",
            content="keep me",
            user_id="user-a",
        )

        deleted = delete_chat_session(
            session,
            course_id="course-a",
            session_id="session-a",
            user_id="user-a",
        )

        assert deleted == 3
        assert _count_messages(session, course_id="course-a") == 1
        assert _count_sessions(session, course_id="course-a") == 1
        assert session.get(ChatSession, "session-b") is not None


def test_clear_messages_by_course_bulk_deletes_course_sessions() -> None:
    with _session() as session:
        create_chat_session(
            session,
            course_id="course-a",
            session_id="session-a",
            title="Session A",
            user_id="user-a",
        )
        create_chat_session(
            session,
            course_id="course-b",
            session_id="session-b",
            title="Session B",
            user_id="user-a",
        )
        create_chat_message(
            session,
            course_id="course-a",
            session_id="session-a",
            role="user",
            content="delete me",
            user_id="user-a",
        )
        create_chat_message(
            session,
            course_id="course-b",
            session_id="session-b",
            role="user",
            content="keep me",
            user_id="user-a",
        )

        deleted = clear_messages_by_course(session, "course-a", user_id="user-a")

        assert deleted == 1
        assert _count_messages(session, course_id="course-a") == 0
        assert _count_messages(session, course_id="course-b") == 1
        assert _count_sessions(session, course_id="course-a") == 0
        assert _count_sessions(session, course_id="course-b") == 1


def test_clear_messages_by_course_with_session_id_preserves_session_rows() -> None:
    with _session() as session:
        for session_id in ("session-a", "session-b"):
            create_chat_session(
                session,
                course_id="course-a",
                session_id=session_id,
                title=session_id,
                user_id="user-a",
            )
        create_chat_message(
            session,
            course_id="course-a",
            session_id="session-a",
            role="user",
            content="delete a1",
            user_id="user-a",
        )
        create_chat_message(
            session,
            course_id="course-a",
            session_id="session-a",
            role="assistant",
            content="delete a2",
            user_id="user-a",
        )
        create_chat_message(
            session,
            course_id="course-a",
            session_id="session-b",
            role="user",
            content="keep b1",
            user_id="user-a",
        )

        deleted = clear_messages_by_course(
            session,
            "course-a",
            session_id="session-a",
            user_id="user-a",
        )

        assert deleted == 2
        assert _count_messages(session, course_id="course-a") == 1
        assert _count_sessions(session, course_id="course-a") == 2
        assert session.get(ChatSession, "session-a") is not None
        assert session.get(ChatSession, "session-b") is not None
        assert _message_contents(session, course_id="course-a") == ["keep b1"]


def test_bulk_delete_operations_are_scoped_to_user_id() -> None:
    with _session() as session:
        for user_id, session_id, content in (
            ("user-a", "session-a", "delete user a"),
            ("user-b", "session-b", "keep user b"),
        ):
            create_chat_session(
                session,
                course_id="course-a",
                session_id=session_id,
                title=session_id,
                user_id=user_id,
            )
            create_chat_message(
                session,
                course_id="course-a",
                session_id=session_id,
                role="user",
                content=content,
                user_id=user_id,
            )

        deleted = clear_messages_by_course(session, "course-a", user_id="user-a")

        assert deleted == 1
        assert _count_messages(session, course_id="course-a") == 1
        assert _count_sessions(session, course_id="course-a") == 1
        assert session.get(ChatSession, "session-a") is None
        assert session.get(ChatSession, "session-b") is not None
        assert _message_contents(session, course_id="course-a") == ["keep user b"]
