"""Support helpers for the interact workflow."""

from __future__ import annotations

from app.workflows.interact.support.messages import build_chat_messages, format_retrieval_context_item
from app.workflows.interact.support.retrieval import build_query_embedding, retrieve_context
from app.workflows.interact.support.streaming import SSEEventEmitter, format_sse_event
from app.workflows.interact.support.strategies import build_strategy_instruction, select_teaching_strategy
from app.workflows.interact.support.types import (
    MistakeSummary,
    RecentMessage,
    RetrievedContext,
    WeakPointSummary,
)

__all__ = [
    "MistakeSummary",
    "RecentMessage",
    "RetrievedContext",
    "SSEEventEmitter",
    "WeakPointSummary",
    "build_chat_messages",
    "build_query_embedding",
    "build_strategy_instruction",
    "format_retrieval_context_item",
    "format_sse_event",
    "retrieve_context",
    "select_teaching_strategy",
]
