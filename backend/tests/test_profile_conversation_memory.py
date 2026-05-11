from __future__ import annotations

from sqlmodel import Session, SQLModel, create_engine

from app.models import ChatMessage
from app.workflows.profile.common.lib.conversation_memory import build_conversation_profile_signals


def _session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[ChatMessage.__table__])
    return Session(engine, expire_on_commit=False)


def test_conversation_profile_signals_detect_guided_reasoning_preference() -> None:
    with _session() as session:
        session.add(
            ChatMessage(
                course_id="course_math",
                user_id="user-a",
                session_id="session-a",
                turn_id="turn-1",
                role="user",
                content="这个公式为什么这么推导？请一步一步讲过程。",
                selected_text="公式 A",
            )
        )
        session.add(
            ChatMessage(
                course_id="course_math",
                user_id="user-a",
                session_id="session-a",
                turn_id="turn-2",
                role="user",
                content="这道题的证明思路是怎么来的？",
                selected_text="证明题",
            )
        )
        session.commit()

        signals = build_conversation_profile_signals(
            session,
            user_id="user-a",
            course_id="course_math",
        )

    assert signals.message_count == 2
    assert signals.selected_text_count == 2
    assert signals.dominant_intent == "guided_reasoning"
    assert signals.explanation_style == "detailed"
    assert "对话偏好：更常请求推导和步骤讲解" in signals.notes
    assert "资料使用：2 次围绕划选内容追问" in signals.notes
