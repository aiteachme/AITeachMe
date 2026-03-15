"""Schemas for chat requests, SSE payloads, and chat history responses."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.schemas.enums import ChatRoleValue


class ChatRequest(BaseModel):
    """Request body for the subject chat endpoint."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "什么是条件概率？",
                "selected_context": "条件概率是指在事件 B 已发生的条件下事件 A 发生的概率。",
                "source_chunk_id": 12,
            }
        }
    )

    question: str = Field(description="用户当前提问内容。", examples=["什么是条件概率？"])
    selected_context: str | None = Field(
        default=None,
        description="前端划词提问时附带的高优先级上下文片段。",
    )
    source_chunk_id: int | None = Field(
        default=None,
        description="selected_context 对应的知识切块 ID。",
        examples=[12],
    )


class SSETokenEvent(BaseModel):
    """Payload emitted by `event: token` SSE frames."""

    model_config = ConfigDict(json_schema_extra={"example": {"content": "条件概率"}})

    content: str = Field(description="当前增量生成的文本片段。")


class SSEDoneEvent(BaseModel):
    """Payload emitted by the final `event: done` SSE frame."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "turn_id": "5c4d8b2e-1453-4a5f-b7ad-b558e3a1df6d",
                "contexts": [
                    {
                        "chunk_id": 12,
                        "title": "条件概率",
                        "header_path": "第一章 > 1.2 条件概率",
                        "score": 0.9821,
                    }
                ],
            }
        }
    )

    turn_id: str = Field(description="本轮对话的 turn_id。")
    contexts: list[dict] | None = Field(
        default=None,
        description="用于生成回答的检索上下文摘要列表。",
    )


class SSEErrorEvent(BaseModel):
    """Payload emitted by `event: error` SSE frames."""

    model_config = ConfigDict(
        json_schema_extra={"example": {"detail": "LLM 调用失败", "error_code": "STREAM_ERROR"}}
    )

    detail: str = Field(description="流式生成失败原因。")
    error_code: str = Field(description="流式响应错误码。", examples=["STREAM_ERROR"])


class ChatMessageItem(BaseModel):
    """Single persisted chat message item returned by history endpoints."""

    id: int = Field(description="消息记录 ID。", examples=[1001])
    turn_id: str = Field(description="同一轮用户问答共享的 turn_id。")
    role: ChatRoleValue = Field(description="消息角色。")
    content: str = Field(description="消息正文内容。")
    contexts: list[dict] | None = Field(
        default=None,
        description="仅助手消息可能携带的检索上下文摘要。",
    )
    created_at: datetime = Field(description="消息创建时间（UTC）。")


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
                        "content": "我们先从事件 A 和 B 的关系来想。",
                        "contexts": None,
                        "created_at": "2026-03-15T08:00:00Z",
                    }
                ],
                "total": 1,
            }
        }
    )

    items: list[ChatMessageItem] = Field(description="当前分页内的消息列表。")
    total: int = Field(description="历史消息总数。", ge=0)
