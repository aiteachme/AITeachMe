"""History-loading node builders for the interact workflow.

Reads DB: ``chat_message`` plus active mastery/attempt summaries.
Writes DB: none.
Writes FS: none.
Idempotency: read-only node; repeated runs return the latest persisted history snapshot.
"""

from __future__ import annotations

from sqlmodel import Session

from app.core.config import get_settings
from app.repositories import profile_repo
from app.repositories.chats_repo import get_recent_turns
from app.services.presenters import mastery_to_text
from app.workflows.common.context import WorkflowContext
from app.workflows.interact.state import InteractWorkflowState
from app.workflows.interact.support.types import (
    MistakeSummary,
    RecentMessage,
    WeakPointSummary,
)


def build_load_history_state_node(*, context: WorkflowContext, session: Session):
    """Build the node that loads history, weak points, and recent mistakes."""

    settings = get_settings()
    workflow_logger = context.get_logger()

    def load_history_state(state: InteractWorkflowState) -> InteractWorkflowState:
        recent_messages = [
            RecentMessage(role=item.role, content=item.content)
            for item in get_recent_turns(
                session,
                state["subject"],
                user_id=state["user_id"],
                n_turns=settings.chat_history_turns,
                session_id=state.get("session_id"),
            )
        ]
        weak_points_from_mastery = profile_repo.list_weak_node_summaries(
            session,
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
            session,
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
