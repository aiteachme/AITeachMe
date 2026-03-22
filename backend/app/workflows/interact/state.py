"""State types for the interact workflow."""

from __future__ import annotations

from typing import TypedDict

from app.core.strategies import StrategyMode
from app.schemas.chats import ChatContextItem
from app.schemas.llm import ChatMessage
from app.workflows.interact.support.types import (
    MistakeSummary,
    RetrievedContext,
    RecentMessage,
    WeakPointSummary,
)


class InteractWorkflowState(TypedDict, total=False):
    subject: str
    question: str
    selected_context: str | None
    source_chunk_id: int | None
    recent_messages: list[RecentMessage]
    weak_points: list[WeakPointSummary]
    recent_mistakes: list[MistakeSummary]
    retrieval_results: list[RetrievedContext]
    contexts: list[ChatContextItem] | None
    strategy_mode: StrategyMode
    messages: list[ChatMessage]
    assistant_response: str
    turn_id: str
    stream_interrupted: bool
    error: str | None
