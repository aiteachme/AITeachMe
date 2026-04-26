from sqlmodel import SQLModel, Session, create_engine

from app.api import chats
from app.models import ChatSession  # noqa: F401 - imports chat tables into metadata
from app.repositories.chats_repo import create_message_pair
from app.utils.subject import GLOBAL_SUBJECT
from app.workflows.interact.chat import create_session, list_chat_history, list_chat_sessions


def test_chat_subject_accepts_global_aliases() -> None:
    assert chats._normalize_chat_subject("") == GLOBAL_SUBJECT
    assert chats._normalize_chat_subject(" global ") == GLOBAL_SUBJECT
    assert chats._normalize_chat_subject("_global") == GLOBAL_SUBJECT
    assert chats._normalize_chat_subject("__global__") == GLOBAL_SUBJECT
    assert chats._normalize_chat_subject("subj_123456789abc") == "subj_123456789abc"


def test_global_chat_scope_does_not_require_subject_record(monkeypatch) -> None:
    calls: list[object] = []
    monkeypatch.setattr(chats, "get_subject_record", lambda *args, **kwargs: calls.append((args, kwargs)))

    assert chats._prepare_chat_subject(object(), raw_subject="global", user_id="user-1") == GLOBAL_SUBJECT
    assert calls == []


def test_global_chat_sessions_are_isolated_from_subject_sessions() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        created = create_session(
            session,
            subject=GLOBAL_SUBJECT,
            user_id="user-1",
            title="Global chat",
            source=None,
        )
        create_message_pair(
            session,
            subject=GLOBAL_SUBJECT,
            user_id="user-1",
            session_id=created.id,
            user_content="hello",
            assistant_content="hi",
        )

        global_sessions = list_chat_sessions(
            session,
            subject=GLOBAL_SUBJECT,
            user_id="user-1",
            page=1,
            size=10,
        )
        subject_sessions = list_chat_sessions(
            session,
            subject="subj_123456789abc",
            user_id="user-1",
            page=1,
            size=10,
        )
        global_history = list_chat_history(
            session,
            subject=GLOBAL_SUBJECT,
            user_id="user-1",
            page=1,
            size=10,
            session_id=created.id,
        )

    assert global_sessions.total == 1
    assert global_sessions.items[0].message_count == 2
    assert subject_sessions.total == 0
    assert global_history.total == 2
