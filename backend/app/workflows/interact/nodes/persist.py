"""Persistence node builders for the interact workflow.

Reads DB: none.
Writes DB: ``chat_message`` user/assistant turn pairs with serialized citation contexts.
Writes FS: none.
Idempotency: should run once per completed turn; rerunning would create another persisted pair.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator

from sqlmodel import Session

from app.repositories.chats_repo import create_message_pair
from app.shared.infra.database import managed_session
from app.workflows.common.context import WorkflowContext
from app.workflows.interact.state import InteractWorkflowState


@contextmanager
def _node_session(session_override: Session | None) -> Generator[Session, None, None]:
    if session_override is not None:
        yield session_override
        return
    with managed_session() as session:
        yield session


def build_persist_turn_node(*, context: WorkflowContext, session: Session | None = None):
    """Build the node that persists the final chat turn."""

    workflow_logger = context.get_logger()

    def persist_turn(state: InteractWorkflowState) -> InteractWorkflowState:
        if state.get("error") or state.get("stream_interrupted"):
            workflow_logger.info(
                "interact_persist_skipped",
                has_error=bool(state.get("error")),
                stream_interrupted=bool(state.get("stream_interrupted")),
            )
            return state

        assistant_response = state.get("assistant_response", "").strip()
        if not assistant_response:
            workflow_logger.warning("interact_empty_response")
            return {
                **state,
                "error": "Assistant response is empty.",
            }
        session_id = state.get("session_id")
        if not session_id:
            workflow_logger.error("interact_missing_session_id")
            return {
                **state,
                "error": "Missing session_id for chat persistence.",
            }

        with _node_session(session) as db_session:
            _, assistant_message = create_message_pair(
                db_session,
                subject=state["subject"],
                user_id=state["user_id"],
                session_id=session_id,
                user_content=state["question"],
                assistant_content=assistant_response,
                contexts=[
                    item.model_dump()
                    for item in (state.get("contexts") or [])
                ] or None,
            )
        workflow_logger.info(
            "interact_turn_persisted",
            turn_id=assistant_message.turn_id,
            citation_count=len(state.get("contexts") or []),
        )
        return {
            **state,
            "turn_id": assistant_message.turn_id,
        }

    return persist_turn
