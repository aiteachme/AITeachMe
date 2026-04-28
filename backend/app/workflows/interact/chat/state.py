"""State types for the interact workflow."""

from __future__ import annotations

from typing import TypedDict

from app.shared.infra.strategies import StrategyMode
from app.schemas.chats import ChatContextItem, ChatSelectionContext
from app.schemas.llm import ChatMessage
from app.workflows.interact.chat.lib.execution import InteractExecutionMode
from app.workflows.interact.chat.lib.types import (
    MistakeSummary,
    RetrievedContext,
    RecentMessage,
    SubjectContextSummary,
    WeakPointSummary,
)


class InteractWorkflowState(TypedDict, total=False):
    subject_id: str
    user_id: str
    session_id: str | None
    session_title: str | None
    session_created: bool
    question: str
    source: str | None
    anchor_id: str | None
    selected_text: str | None
    selected_context: str | None
    selection_context: ChatSelectionContext | None
    source_chunk_id: int | None
    recent_messages: list[RecentMessage]
    subject_context: SubjectContextSummary
    weak_points: list[WeakPointSummary]
    recent_mistakes: list[MistakeSummary]
    retrieval_results: list[RetrievedContext]
    contexts: list[ChatContextItem] | None
    strategy_mode: StrategyMode
    execution_mode: InteractExecutionMode
    messages: list[ChatMessage]
    assistant_response: str
    turn_id: str
    stream_interrupted: bool
    error: str | None
