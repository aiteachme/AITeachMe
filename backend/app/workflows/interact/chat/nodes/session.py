"""Chat session persistence nodes for the interact workflow.

Reads DB: ``chat_session`` for existing-session lookup and title checks.
Writes DB: creates missing chat sessions and touches title/last-message metadata
after a completed turn.
Writes FS: none.
Idempotency: resolution is safe to repeat for an existing session; creating a
missing session intentionally creates one new chat container for the request.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Generator

from sqlmodel import Session

from app.models import ChatSession
from app.repositories.chats_repo import (
    create_chat_session,
    get_chat_session,
    touch_chat_session,
)
from app.shared.infra.database import managed_session
from app.shared.infra.workflow.context import WorkflowContext
from app.workflows.interact.chat.lib.sessioning import (
    TITLE_RESOLVE_TIMEOUT_S,
    build_session_title,
    generate_session_title,
    should_generate_session_title,
)
from app.workflows.interact.chat.lib.streaming import SSEEventEmitter
from app.workflows.interact.chat.state import InteractWorkflowState


@contextmanager
def _node_session(session_override: Session | None) -> Generator[Session, None, None]:
    if session_override is not None:
        yield session_override
        return
    with managed_session() as session:
        yield session


async def _emit_status(
    emitter: SSEEventEmitter | None,
    stage: str,
    detail: str,
    **extra: object,
) -> None:
    if emitter is None:
        return
    await emitter.emit_status(stage=stage, detail=detail, **extra)


def build_resolve_chat_session_node(
    *,
    context: WorkflowContext,
    session: Session | None = None,
    emitter: SSEEventEmitter | None = None,
):
    """Build the node that resolves or creates the chat session for this turn."""

    workflow_logger = context.get_logger()

    async def resolve_chat_session(state: InteractWorkflowState) -> InteractWorkflowState:
        requested_session_id = str(state.get("session_id") or "").strip()
        with _node_session(session) as db_session:
            existing = _load_requested_session(
                db_session,
                state=state,
                requested_session_id=requested_session_id,
            )
            if existing is None:
                resolved = create_chat_session(
                    db_session,
                    subject=state["subject"],
                    user_id=state["user_id"],
                    source=state.get("source"),
                    title="New Chat",
                )
                created = True
            else:
                resolved = existing
                created = False

        workflow_logger.info(
            "interact_session_resolved",
            session_id=resolved.id,
            session_created=created,
            requested_session_found=existing is not None,
        )
        await _emit_status(
            emitter,
            "session_resolved",
            "Chat session resolved.",
            session_id=resolved.id,
            session_created=created,
        )
        return {
            **state,
            "session_id": resolved.id,
            "session_title": resolved.title,
            "session_created": created,
        }

    return resolve_chat_session


def build_finalize_chat_session_node(
    *,
    context: WorkflowContext,
    session: Session | None = None,
):
    """Build the node that updates chat-session metadata after persistence."""

    workflow_logger = context.get_logger()

    async def finalize_chat_session(state: InteractWorkflowState) -> InteractWorkflowState:
        if state.get("error") or state.get("stream_interrupted"):
            workflow_logger.info(
                "interact_session_finalize_skipped",
                has_error=bool(state.get("error")),
                stream_interrupted=bool(state.get("stream_interrupted")),
            )
            return state

        session_id = str(state.get("session_id") or "").strip()
        if not session_id:
            workflow_logger.error("interact_finalize_missing_session_id")
            return state

        current_title = _load_current_title(
            session,
            state=state,
            session_id=session_id,
        )
        next_title = await _resolve_next_title(
            state,
            current_title=current_title,
        )
        with _node_session(session) as db_session:
            touched = touch_chat_session(
                db_session,
                subject=state["subject"],
                user_id=state["user_id"],
                session_id=session_id,
                title=next_title,
            )

        if touched is None:
            workflow_logger.warning(
                "interact_session_finalize_missing_session",
                session_id=session_id,
            )
            return {
                **state,
                "session_title": next_title or current_title or state.get("session_title"),
            }

        workflow_logger.info(
            "interact_session_finalized",
            session_id=touched.id,
            title_updated=bool(next_title),
        )
        return {
            **state,
            "session_title": touched.title,
        }

    return finalize_chat_session


def _load_requested_session(
    session: Session,
    *,
    state: InteractWorkflowState,
    requested_session_id: str,
) -> ChatSession | None:
    if not requested_session_id:
        return None
    return get_chat_session(
        session,
        subject=state["subject"],
        user_id=state["user_id"],
        session_id=requested_session_id,
    )


def _load_current_title(
    session_override: Session | None,
    *,
    state: InteractWorkflowState,
    session_id: str,
) -> str:
    with _node_session(session_override) as db_session:
        existing = get_chat_session(
            db_session,
            subject=state["subject"],
            user_id=state["user_id"],
            session_id=session_id,
        )
        return existing.title if existing is not None else str(state.get("session_title") or "")


async def _resolve_next_title(
    state: InteractWorkflowState,
    *,
    current_title: str,
) -> str | None:
    if not should_generate_session_title(current_title, state["question"]):
        return None
    try:
        return await asyncio.wait_for(
            generate_session_title(
                subject=state["subject"],
                question=state["question"],
                selected_text=(
                    state.get("selected_text")
                    or _selection_text(state.get("selection_context"))
                ),
                assistant_response=state.get("assistant_response", ""),
            ),
            timeout=TITLE_RESOLVE_TIMEOUT_S,
        )
    except Exception:
        return build_session_title(state["question"])


def _selection_text(selection_context: object | None) -> str:
    if selection_context is None:
        return ""
    return str(getattr(selection_context, "selected_text", "") or "")


__all__ = [
    "build_finalize_chat_session_node",
    "build_resolve_chat_session_node",
]
