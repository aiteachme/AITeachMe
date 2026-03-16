"""Schemas for chat requests, SSE payloads, and chat history responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginationParams
from app.schemas.enums import ChatRoleValue


class ChatSendRequest(BaseModel):
    """Request body for the subject chat send endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "What is conditional probability?",
                "selected_context": "Conditional probability describes the probability of A given that B has happened.",
                "source_chunk_id": 12,
            }
        }
    )

    question: str = Field(description="Current user question.", examples=["What is conditional probability?"])
    selected_context: str | None = Field(default=None, description="Highlighted context snippet selected by the user.")
    source_chunk_id: int | None = Field(default=None, description="Chunk identifier for the highlighted context.", examples=[12])


class ChatListRequest(PaginationParams):
    pass


class SSETokenEvent(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"content": "Conditional probability"}})

    content: str = Field(description="Incremental assistant text chunk.")


class SSEDoneEvent(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "turn_id": "5c4d8b2e-1453-4a5f-b7ad-b558e3a1df6d",
                "contexts": [
                    {
                        "chunk_id": 12,
                        "title": "Conditional Probability",
                        "header_path": "Chapter 1 > 1.2 Conditional Probability",
                        "score": 0.9821,
                    }
                ],
            }
        }
    )

    turn_id: str = Field(description="Conversation turn identifier.")
    contexts: list[dict] | None = Field(default=None, description="Retrieved context summaries used for the final answer.")


class SSEErrorEvent(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "LLM call failed", "error_code": "STREAM_ERROR"}}
    )

    detail: str = Field(description="Reason the streamed response failed.")
    error_code: str = Field(description="Stable error code for stream failures.", examples=["STREAM_ERROR"])


class ChatMessageItem(BaseModel):
    """Single persisted chat message item returned by history endpoints."""

    id: int = Field(description="Message identifier.", examples=[1001])
    turn_id: str = Field(description="Shared turn identifier for the user and assistant messages.")
    role: ChatRoleValue = Field(description="Message role.")
    content: str = Field(description="Message content.")
    contexts: list[dict] | None = Field(default=None, description="Retrieved contexts stored with assistant messages.")
    created_at: datetime = Field(description="Message creation timestamp in UTC.")


class ChatHistoryResponse(BaseModel):
    """Paginated response for historical chat messages."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "items": [
                    {
                        "id": 1001,
                        "turn_id": "5c4d8b2e-1453-4a5f-b7ad-b558e3a1df6d",
                        "role": "assistant",
                        "content": "Let's reason about events A and B first.",
                        "contexts": None,
                        "created_at": "2026-03-15T08:00:00Z",
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[ChatMessageItem] = Field(description="Current page of chat messages.")
    total: int = Field(description="Total number of historical messages.", ge=0)
