"""History-loading node builders for the interact workflow.

Reads DB: ``chat_message`` plus active mastery/attempt summaries.
Writes DB: none.
Writes FS: none.
Idempotency: read-only node; repeated runs return the latest persisted history snapshot.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlmodel import Session

from app.shared.infra.settings import get_settings
from app.shared.infra.database import managed_session
from app.repositories import profile_repo
from app.repositories.chats_repo import get_recent_turns
from app.utils.presenters import mastery_to_text
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.interact.chat.state import InteractWorkflowState
from app.workflows.interact.chat.lib.types import (
    MistakeSummary,
    RecentMessage,
    WeakPointSummary,
)


@contextmanager
def _node_session(session_override: Session | None) -> Generator[Session, None, None]:
    if session_override is not None:
        yield session_override
        return
    with managed_session() as session:
        yield session


def build_load_history_state_node(*, context: WorkflowContext, session: Session | None = None):
    """Build the node that loads history, weak points, and recent mistakes."""

    settings = get_settings()
    workflow_logger = context.get_logger()

    def load_history_state(state: InteractWorkflowState) -> InteractWorkflowState:
        with _node_session(session) as db_session:
            recent_messages = [
                RecentMessage(role=item.role, content=item.content)
                for item in get_recent_turns(
                    db_session,
                    state["subject"],
                    user_id=state["user_id"],
                    n_turns=settings.chat.history_turns,
                    session_id=state.get("session_id"),
                )
            ]
            weak_points_from_mastery = profile_repo.list_weak_node_summaries(
                db_session,
                user_id=state["user_id"],
                subject=state["subject"],
                limit=10,
            )
            weak_points = [
                WeakPointSummary(
                    knowledge_point=name,
                    mastery_text=mastery_to_text(mastery),
                )
                for name, mastery in weak_points_from_mastery
            ]

            recent_mistakes_raw = profile_repo.list_recent_wrong_attempt_summaries(
                db_session,
                user_id=state["user_id"],
                subject=state["subject"],
                limit=5,
            )
            recent_mistakes = [MistakeSummary.model_validate(item) for item in recent_mistakes_raw]
        workflow_logger.info(
            "interact_history_loaded",
            recent_message_count=len(recent_messages),
            weak_point_count=len(weak_points),
            recent_mistake_count=len(recent_mistakes),
        )
        return {
            **state,
            "recent_messages": recent_messages,
            "weak_points": weak_points,
            "recent_mistakes": recent_mistakes,
        }

    return load_history_state

