"""Chat API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PageParams
from app.schemas.enums import ChatRoleValue


class ChatContextItem(BaseModel):
    """One retrieval citation attached to an assistant message."""

    chunk_id: int = Field(description="Knowledge chunk ID.")
    document_id: int = Field(description="Document ID.")
    title: str = Field(description="Chunk title.")
    header_path: str = Field(description="Chunk header path.")
    score: float = Field(description="Retrieval score.")


class ChatSendRequest(BaseModel):
    """Request body for sending one chat message."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "什么是条件概率？",
                "selected_context": "条件概率表示在 B 已经发生的前提下 A 发生的概率。",
                "source_chunk_id": 12,
            }
        }
    )

    question: str = Field(description="Current user question.")
    selected_context: str | None = Field(default=None, description="Optional highlighted context.")
    source_chunk_id: int | None = Field(default=None, description="Optional source chunk ID for the highlighted context.")


class ChatListRequest(PageParams):
    """Pagination request for chat history."""


class ChatClearRequest(BaseModel):
    """Request body for clearing chat history."""

    model_config = ConfigDict(json_schema_extra={"example": {}})


class ChatClearData(BaseModel):
    """Result payload for clearing chat history."""

    cleared: bool = Field(description="Whether the history was cleared.")
    deleted_count: int = Field(description="Deleted message count.", ge=0)


class SSETokenEvent(BaseModel):
    """SSE token event payload."""

    content: str = Field(description="Incremental assistant text.")


class SSEDoneEvent(BaseModel):
    """SSE done event payload."""

    turn_id: str = Field(description="Persisted turn ID.")
    contexts: list[ChatContextItem] | None = Field(default=None, description="Retrieved citation list.")


class SSEErrorEvent(BaseModel):
    """SSE error event payload."""

    detail: str = Field(description="Error detail.")
    error_code: str = Field(description="Stable error code.")


class ChatMessageItem(BaseModel):
    """One persisted chat message."""

    id: int = Field(description="Message ID.")
    turn_id: str = Field(description="Conversation turn ID.")
    role: ChatRoleValue = Field(description="Message role.")
    content: str = Field(description="Message content.")
    contexts: list[ChatContextItem] | None = Field(default=None, description="Assistant citation list.")
    created_at: datetime = Field(description="Created time.")
