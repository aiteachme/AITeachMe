"""对话相关 Schema — ChatRequest、SSE 事件模型、ChatHistoryResponse"""

from datetime import datetime
from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    selected_context: str | None = None
    source_chunk_id: int | None = None


class SSETokenEvent(BaseModel):
    """event: token"""
    content: str


class SSEDoneEvent(BaseModel):
    """event: done"""
    turn_id: str
    contexts: list[dict] | None = None


class SSEErrorEvent(BaseModel):
    """event: error"""
    detail: str
    error_code: str


class ChatMessageItem(BaseModel):
    id: int
    turn_id: str
    role: str
    content: str
    contexts: list[dict] | None = None
    created_at: datetime


class ChatHistoryResponse(BaseModel):
    items: list[ChatMessageItem]
    total: int
